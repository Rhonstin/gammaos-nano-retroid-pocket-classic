"""Host tests for the dev.26 application integration (no device, no network)."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import retroarch_payload  # noqa: E402


def nano_config(*systems):
    return {"version": 1, "systems": [dict(s) for s in systems]}


PSX = {"id": "psx", "builtin": True, "enabled": True, "order": 10, "displayName": "PlayStation",
       "launchType": "libretro-core", "coreSo": "pcsx_rearmed_libretro_android.so", "romDir": "psx"}
NES = {"id": "nes", "builtin": True, "enabled": True, "order": 0, "displayName": "NES",
       "launchType": "libretro-core", "coreSo": "nestopia_libretro_android.so", "romDir": "nes"}


@unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "JDK required")
class ClassicSystemsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = Path(tempfile.mkdtemp())
        subprocess.run(["javac", "--release", "8", "-d", cls.build, ROOT / "tools/android/ClassicSystems.java"],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.build)

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.cores = self.dir / "cores"
        self.cores.mkdir()
        (self.cores / "swanstation_libretro_android.so").write_bytes(b"core")
        self.nano = self.dir / "nano_systems.json"
        self.state = self.dir / "state.json"
        self.packages = self.dir / "packages.list"
        self.packages.write_text("com.armsx2 10073 0 /data/user/0/com.armsx2 default:targetSdkVersion=37 none 0 1\n")
        self.defs = self.dir / "defs.json"
        self.definitions = json.loads((ROOT / "device/classic-systems.json").read_text())
        self.defs.write_text(json.dumps(self.definitions))

    def tearDown(self):
        shutil.rmtree(self.dir)

    def run_helper(self):
        return subprocess.run(["java", "-cp", self.build, "ClassicSystems", self.defs, self.nano, self.state,
                               self.packages, self.cores], capture_output=True, text=True)

    def systems(self):
        return {s["id"]: s for s in json.loads(self.nano.read_text())["systems"]}

    def test_waits_for_nano_to_seed_its_config(self):
        self.assertEqual(self.run_helper().returncode, 3)
        self.assertFalse(self.state.exists())

    def test_adds_only_installed_emulators_after_existing_order(self):
        self.nano.write_text(json.dumps(nano_config(NES, PSX)))
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        systems = self.systems()
        self.assertIn("ps2", systems)
        self.assertNotIn("steam", systems)            # DroidDeck not installed
        self.assertNotIn("saturn", systems)           # yabasanshiro core absent
        self.assertEqual(systems["ps2"]["order"], 11)
        self.assertNotIn("requiresPackage", systems["ps2"])
        self.assertEqual(systems["ps2"]["scanSources"][0]["value"], "/data/media/0/ROMs/ps2")
        self.assertEqual(systems["psx"]["coreSo"], "pcsx_rearmed_libretro_android.so")  # no BIOS

    def test_user_removal_is_final_and_rerun_is_idempotent(self):
        self.nano.write_text(json.dumps(nano_config(NES, PSX)))
        self.run_helper()
        first = self.nano.read_text()
        self.assertIn("unchanged", self.run_helper().stdout)
        self.assertEqual(self.nano.read_text(), first)
        config = json.loads(first)
        config["systems"] = [s for s in config["systems"] if s["id"] != "ps2"]
        self.nano.write_text(json.dumps(config))
        self.run_helper()
        self.assertNotIn("ps2", self.systems())

    def test_refreshes_only_untouched_definitions(self):
        self.nano.write_text(json.dumps(nano_config(NES, PSX)))
        self.run_helper()
        for system in self.definitions["systems"]:
            if system["id"] == "ps2":
                system["intentTemplate"] += " --ez fullscreen true"
        self.defs.write_text(json.dumps(self.definitions))
        self.assertIn("refreshed ps2", self.run_helper().stdout)
        config = json.loads(self.nano.read_text())
        for system in config["systems"]:
            if system["id"] == "ps2":
                system["displayName"] = "My PS2"
        self.nano.write_text(json.dumps(config))
        for system in self.definitions["systems"]:
            if system["id"] == "ps2":
                system["intentTemplate"] += " --ez other true"
        self.defs.write_text(json.dumps(self.definitions))
        self.run_helper()
        self.assertEqual(self.systems()["ps2"]["displayName"], "My PS2")
        self.assertNotIn("other", self.systems()["ps2"]["intentTemplate"])

    def test_psx_migrates_once_when_bios_exists(self):
        bios = self.dir / "scph5501.bin"
        for migration in self.definitions["migrations"]:
            migration["whenAnyFile"] = [str(bios)]
        self.defs.write_text(json.dumps(self.definitions))
        self.nano.write_text(json.dumps(nano_config(NES, PSX)))
        self.run_helper()
        self.assertEqual(self.systems()["psx"]["coreSo"], "pcsx_rearmed_libretro_android.so")
        bios.write_bytes(b"bios")
        self.run_helper()
        self.assertEqual(self.systems()["psx"]["coreSo"], "swanstation_libretro_android.so")
        config = json.loads(self.nano.read_text())
        for system in config["systems"]:
            if system["id"] == "psx":
                system["coreSo"] = "pcsx_rearmed_libretro_android.so"   # user switched back
        self.nano.write_text(json.dumps(config))
        self.run_helper()
        self.assertEqual(self.systems()["psx"]["coreSo"], "pcsx_rearmed_libretro_android.so")


class RetroArchPayloadTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir)

    def member(self, archive, name, data=None, mode=0o600):
        info = tarfile.TarInfo(name)
        info.uid, info.gid, info.uname, info.gname = 10188, 10188, "u0_a188", "u0_a188"
        if data is None:
            info.type, info.mode = tarfile.DIRTYPE, 0o700
            archive.addfile(info)
        else:
            info.size, info.mode = len(data), mode
            archive.addfile(info, io.BytesIO(data))

    def pinned(self, name, members):
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as bundle:
            for member, data in members.items():
                bundle.writestr(member, data)
        return {"file": name, "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def test_replaces_overlays_and_keeps_custom_files(self):
        app = retroarch_payload.APP
        plain = self.dir / "orig.tar"
        with tarfile.open(plain, "w") as archive:
            for directory in ("", "/cores", "/shaders", "/shaders/shaders_slang", "/shaders/Sharp-Shimmerless"):
                self.member(archive, app + directory)
            self.member(archive, app + "/cores/snes9x_libretro_android.so", b"old core", 0o700)
            self.member(archive, app + "/cores/fake08_libretro_android.so", b"stock only", 0o700)
            self.member(archive, app + "/shaders/shaders_slang/old.slangp", b"old preset")
            self.member(archive, app + "/shaders/Sharp-Shimmerless/custom.slangp", b"gammaos")
        source = self.dir / "orig.tar.xz"
        with source.open("wb") as sink:
            subprocess.run(["xz", "-k", "-c", plain], stdout=sink, check=True)
        lock = {"retroarch_payload": {
            "cores": [self.pinned("cores/snes9x_libretro_android.so.zip", {"snes9x_libretro_android.so": b"new core"})],
            "assets": [self.pinned("assets/shaders_slang.zip", {"old.slangp": b"new preset",
                                                                 "handheld/lcd.slangp": b"added"}),
                       self.pinned("assets/autoconfig.zip", {"android/pad.cfg": b"pad", "udev/pad.cfg": b"skip"})]}}
        output = self.dir / "new.tar.xz"
        stats = retroarch_payload.build(source, output, lock, self.dir)
        self.assertEqual(stats["replaced"], 2)
        with tarfile.open(output) as archive:
            names = {m.name: m for m in archive.getmembers()}
            read = lambda n: archive.extractfile(names[n]).read()
            self.assertEqual(read(app + "/cores/snes9x_libretro_android.so"), b"new core")
            self.assertEqual(names[app + "/cores/snes9x_libretro_android.so"].mode, 0o700)
            self.assertEqual(read(app + "/cores/fake08_libretro_android.so"), b"stock only")
            self.assertEqual(read(app + "/shaders/shaders_slang/old.slangp"), b"new preset")
            self.assertEqual(read(app + "/shaders/Sharp-Shimmerless/custom.slangp"), b"gammaos")
            added = names[app + "/shaders/shaders_slang/handheld/lcd.slangp"]
            self.assertEqual((added.uid, added.gid, added.mode), (10188, 10188, 0o600))
            self.assertTrue(names[app + "/shaders/shaders_slang/handheld"].isdir())
            self.assertIn(app + "/autoconfig/android/pad.cfg", names)
            self.assertNotIn(app + "/autoconfig/udev/pad.cfg", names)

    def test_rejects_unverified_inputs(self):
        lock = {"retroarch_payload": {"cores": [{"file": "missing.zip", "size": 1, "sha256": "0" * 64}],
                                      "assets": []}}
        (self.dir / "missing.zip").write_bytes(b"xx")
        with self.assertRaises(RuntimeError):
            retroarch_payload.planned_files(lock, self.dir)


class ApplicationLockTest(unittest.TestCase):
    def test_lock_is_consistent(self):
        lock = json.loads((ROOT / "apps.lock.json").read_text())
        packages, paths = set(), set()
        for app in lock["apps"]:
            self.assertRegex(app["sha256"], "^[0-9a-f]{64}$")
            self.assertTrue(app["image_path"].startswith("/system/etc/"))
            self.assertNotIn("|", app["image_path"])
            self.assertLessEqual(set(app["grants"]), {"storage", "notifications"})
            self.assertIn(app["role"], ("update", "add"))
            if app["role"] == "add":
                self.assertTrue(app["image_path"].startswith("/system/etc/classic-apps/"))
            packages.add(app["package"])
            paths.add(app["image_path"])
        self.assertEqual(len(packages), len(lock["apps"]))
        self.assertEqual(len(paths), len(lock["apps"]))
        core_files = [c["file"] for c in lock["retroarch_payload"]["cores"]]
        self.assertEqual(len(core_files), len(set(core_files)))

    def test_systems_reference_locked_packages(self):
        lock = json.loads((ROOT / "apps.lock.json").read_text())
        packages = {app["package"] for app in lock["apps"]} | set(lock.get("owner_installed", {}))
        self.assertFalse(set(lock.get("owner_installed", {})) & {app["package"] for app in lock["apps"]})
        for system in json.loads((ROOT / "device/classic-systems.json").read_text())["systems"]:
            if "requiresPackage" in system:
                self.assertIn(system["requiresPackage"], packages)
                self.assertEqual(system["package"], system["requiresPackage"])
                self.assertIn("{file.uri}", system["intentTemplate"])
            self.assertTrue(system["icon"]["ref"].startswith("retroarch:"))

    def test_profiles_stay_inside_their_package(self):
        for manifest in (ROOT / "device/profiles-src").glob("*/profile.json"):
            profile = json.loads(manifest.read_text())
            self.assertEqual(manifest.parent.name, profile["package"])
            for target, source in profile["files"].items():
                self.assertIn(profile["package"], target)
                self.assertTrue((manifest.parent / source).is_file())

    def test_scripts_parse(self):
        for script in ("classic-apps.sh", "classic-provision.sh"):
            subprocess.run(["sh", "-n", ROOT / "device" / script], check=True)


class DisplayTweakTest(unittest.TestCase):
    """Runs the script's tweak() and its two calls against sample emulator configs."""

    def run_tweaks(self, data):
        text = (ROOT / "device/classic-apps.sh").read_text()
        body = text[text.index("tweak() {"):text.index('[ "$pending" = 0 ]')]
        body = body.replace("/data/media/0/", data + "/")
        harness = f'set -u\nSTATE="{data}/state"\nmkdir -p "$STATE"\nlog_line() {{ echo "$*"; }}\n{body}'
        return subprocess.run(["sh", "-c", harness], check=True, capture_output=True, text=True).stdout

    def test_turns_off_counters_once_and_waits_for_configs(self):
        with tempfile.TemporaryDirectory() as tmp:
            flycast = Path(tmp, "Android/data/com.flycast.emulator/files/emu.cfg")
            eden = Path(tmp, "Android/data/dev.legacy.eden_emulator/files/config/config.ini")
            flycast.parent.mkdir(parents=True)
            flycast.write_text("[config]\nrend.ShowFPS = yes\nrend.TextureUpscale = 1\n")
            out = self.run_tweaks(tmp)
            self.assertEqual(flycast.read_text(), "[config]\nrend.ShowFPS = no\nrend.TextureUpscale = 1\n")
            self.assertIn("flycast-fps: applied", out)
            self.assertFalse(Path(tmp, "state/tweak-eden-perf-overlay").exists())

            eden.parent.mkdir(parents=True)
            eden.write_text("[Overlay]\nshow_performance_overlay\\default=true\nshow_performance_overlay=true\n")
            flycast.write_text("[config]\nrend.ShowFPS = yes\n")  # owner re-enabled it
            out = self.run_tweaks(tmp)
            self.assertEqual(eden.read_text(),
                             "[Overlay]\nshow_performance_overlay\\default=false\nshow_performance_overlay=false\n")
            self.assertEqual(flycast.read_text(), "[config]\nrend.ShowFPS = yes\n")
            self.assertEqual(out.strip(), "eden-perf-overlay: applied")

    def test_eden_defaults_keep_owner_choices(self):
        text = (ROOT / "device/classic-apps.sh").read_text()
        body = text[text.index("tweak() {"):text.index('[ "$pending" = 0 ]')]
        with tempfile.TemporaryDirectory() as tmp:
            eden = Path(tmp, "Android/data/dev.legacy.eden_emulator/files")
            (eden / "config").mkdir(parents=True)
            driver = Path(tmp, "turnip-axfl3-003-android.zip")
            driver.write_bytes(b"PK zip")
            config = eden / "config/config.ini"
            config.write_text("[Cpu]\ncpu_backend\\default=true\ncpu_backend=1\n"
                              "[GpuDriver]\ndriver_path\\default=true\ndriver_path=\n")
            stubs = ('am() { :; }; chcon() { :; }; chown() { :; }\n'
                     'ls() { echo "u:object_r:test:s0 $2"; }\n'
                     'stat() { echo 1:1; }\n')
            script = body.replace("/data/media/0/", tmp + "/").replace(
                "/system/etc/classic-drivers/turnip-axfl3-003-android.zip", str(driver))
            harness = f'set -u\nSTATE="{tmp}/state"\nmkdir -p "$STATE"\nlog_line() {{ echo "$*"; }}\n{stubs}{script}'
            out = subprocess.run(["sh", "-c", harness], check=True, capture_output=True, text=True).stdout
            self.assertIn("eden-defaults: applied", out)
            self.assertEqual((eden / "gpu_drivers/turnip-axfl3-003-android.zip").read_bytes(), b"PK zip")
            self.assertEqual(config.read_text(),
                             "[Cpu]\ncpu_backend\\default=false\ncpu_backend=0\n[GpuDriver]\n"
                             "driver_path\\default=false\ndriver_path=/storage/emulated/0/Android/data/"
                             "dev.legacy.eden_emulator/files/gpu_drivers/turnip-axfl3-003-android.zip\n")

            # An owner who already chose a driver and NCE keeps both.
            Path(tmp, "state/tweak-eden-defaults").unlink()
            chosen = ("[Cpu]\ncpu_backend\\default=false\ncpu_backend=1\n"
                      "[GpuDriver]\ndriver_path\\default=false\ndriver_path=/x.zip\n")
            config.write_text(chosen)
            subprocess.run(["sh", "-c", harness], check=True, capture_output=True, text=True)
            self.assertEqual(config.read_text(), chosen)


if __name__ == "__main__":
    unittest.main()
