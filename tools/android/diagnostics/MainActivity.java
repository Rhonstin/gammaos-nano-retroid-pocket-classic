package dev.classic.diagnostics;

import android.app.Activity;
import android.os.Bundle;
import android.os.Build;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.media.AudioDeviceInfo;
import org.json.JSONObject;
import org.json.JSONArray;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.ArrayList;

/** Temporary on-device acceptance test; confirmation buttons record human observations. */
public final class MainActivity extends Activity {
    final LinkedHashMap<String,Boolean> buttons = new LinkedHashMap<>();
    final ArrayList<JSONObject> events = new ArrayList<>();
    int corner = 0;
    boolean audioPlayed, audioHeard, vibrationSent, vibrationFelt, finished, busy;
    boolean hasVibrator;
    int controllerId=-1;
    String vibrationRoute="none";
    String audioRoute="none";
    String message = "Натисни всі кнопки; потім торкайся підсвіченого кута.";
    TestView display;

    public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON | WindowManager.LayoutParams.FLAG_FULLSCREEN);
        for (String name : new String[]{"↑","↓","←","→","A","B","X","Y","L1","R1","L2","R2","Start","Select"}) buttons.put(name,false);
        Vibrator vibrator=(Vibrator)getSystemService(VIBRATOR_SERVICE);
        hasVibrator=vibrator!=null && vibrator.hasVibrator();
        display=new TestView(); setContentView(display);
        display.setSystemUiVisibility(View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_FULLSCREEN);
        save();
        if(getIntent().getBooleanExtra("auto_audio",false)) display.postDelayed(()->sound(),1500);
    }

    void event(String kind, String detail) {
        try { JSONObject e=new JSONObject(); e.put("elapsed_ms",android.os.SystemClock.elapsedRealtime());
            e.put("kind",kind); e.put("detail",detail); events.add(e); } catch(Exception ignored) {}
        save(); if(display!=null)display.invalidate();
    }
    void press(String name) { if(buttons.containsKey(name)){buttons.put(name,true);event("button",name);} }
    public boolean dispatchKeyEvent(KeyEvent e) {
        if((e.getSource() & android.view.InputDevice.SOURCE_GAMEPAD)==android.view.InputDevice.SOURCE_GAMEPAD)controllerId=e.getDeviceId();
        String name=null;
        switch(e.getKeyCode()) {
            case KeyEvent.KEYCODE_DPAD_UP:name="↑";break;case KeyEvent.KEYCODE_DPAD_DOWN:name="↓";break;
            case KeyEvent.KEYCODE_DPAD_LEFT:name="←";break;case KeyEvent.KEYCODE_DPAD_RIGHT:name="→";break;
            case KeyEvent.KEYCODE_BUTTON_A:name="A";break;case KeyEvent.KEYCODE_BUTTON_B:name="B";break;
            case KeyEvent.KEYCODE_BUTTON_X:name="X";break;case KeyEvent.KEYCODE_BUTTON_Y:name="Y";break;
            case KeyEvent.KEYCODE_BUTTON_L1:name="L1";break;case KeyEvent.KEYCODE_BUTTON_R1:name="R1";break;
            case KeyEvent.KEYCODE_BUTTON_L2:name="L2";break;case KeyEvent.KEYCODE_BUTTON_R2:name="R2";break;
            case KeyEvent.KEYCODE_BUTTON_START:name="Start";break;case KeyEvent.KEYCODE_BUTTON_SELECT:name="Select";break;
        }
        if(name!=null){if(e.getAction()==KeyEvent.ACTION_DOWN)press(name);return true;}
        if(e.getKeyCode()==KeyEvent.KEYCODE_BACK){event("back",String.valueOf(e.getAction()));return true;}
        return super.dispatchKeyEvent(e);
    }
    public boolean onGenericMotionEvent(MotionEvent e) {
        if((e.getSource() & android.view.InputDevice.SOURCE_JOYSTICK)!=0) {
            controllerId=e.getDeviceId();
            float x=e.getAxisValue(MotionEvent.AXIS_HAT_X), y=e.getAxisValue(MotionEvent.AXIS_HAT_Y);
            if(x<-.5f)press("←");if(x>.5f)press("→");if(y<-.5f)press("↑");if(y>.5f)press("↓");
            if(e.getAxisValue(MotionEvent.AXIS_LTRIGGER)>.5f || e.getAxisValue(MotionEvent.AXIS_BRAKE)>.5f)press("L2");
            if(e.getAxisValue(MotionEvent.AXIS_RTRIGGER)>.5f || e.getAxisValue(MotionEvent.AXIS_GAS)>.5f)press("R2");
            return true;
        }
        return super.onGenericMotionEvent(e);
    }
    void save() {
        try {
            JSONObject r=new JSONObject();r.put("model",Build.MODEL);r.put("sdk",Build.VERSION.SDK_INT);
            r.put("buttons",new JSONObject(buttons));r.put("corners_in_order",corner);
            r.put("audio_played",audioPlayed);r.put("audio_heard_by_user",audioHeard);
            r.put("audio_route",audioRoute);
            r.put("has_vibrator",hasVibrator);r.put("vibration_requested",vibrationSent);r.put("vibration_felt_by_user",vibrationFelt);
            r.put("controller_id",controllerId);r.put("vibration_route",vibrationRoute);
            r.put("finished_by_user",finished);r.put("events",new JSONArray(events));
            File tmp=new File(getFilesDir(),"report.tmp"), dest=new File(getFilesDir(),"report.json");
            try(FileOutputStream f=new FileOutputStream(tmp)){f.write(r.toString(2).getBytes(StandardCharsets.UTF_8));f.getFD().sync();}
            if(!tmp.renameTo(dest))throw new IllegalStateException("report rename failed");
        } catch(Exception e){android.util.Log.e("ClassicDiagnostics","Cannot save report",e);}
    }
    void sound() {
        if(busy)return;busy=true;message="Зараз: лівий, потім правий канал";display.invalidate();
        new Thread(()->{
            AudioTrack track=null;
            try {
                int rate=48000, frames=rate*2;short[] data=new short[frames*2];
                for(int i=0;i<frames;i++){int channel=i<rate?0:1;double phase=2*Math.PI*(channel==0?440:660)*i/rate;
                    double edge=Math.min(1,Math.min((i%rate)/480.0,(rate-1-i%rate)/480.0));
                    data[i*2+channel]=(short)(Math.sin(phase)*6000*Math.max(0,edge));}
                track=new AudioTrack.Builder().setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_GAME).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                    .setAudioFormat(new AudioFormat.Builder().setSampleRate(rate).setChannelMask(AudioFormat.CHANNEL_OUT_STEREO).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                    .setBufferSizeInBytes(data.length*2).setTransferMode(AudioTrack.MODE_STATIC).build();
                if("bluetooth".equals(getIntent().getStringExtra("audio_route"))) {
                    AudioDeviceInfo selected=null;
                    for(AudioDeviceInfo device:((AudioManager)getSystemService(AUDIO_SERVICE)).getDevices(AudioManager.GET_DEVICES_OUTPUTS))
                        if(device.getType()==AudioDeviceInfo.TYPE_BLUETOOTH_A2DP)selected=device;
                    if(selected==null || !track.setPreferredDevice(selected))throw new IllegalStateException("A2DP output unavailable");
                }
                if(track.write(data,0,data.length)!=data.length)throw new IllegalStateException("short audio write");
                track.play();Thread.sleep(250);
                AudioDeviceInfo routed=track.getRoutedDevice();
                audioRoute=routed==null?"unresolved":routed.getType()+":"+routed.getAddress()+":"+routed.getProductName();
                Thread.sleep(2050);
                runOnUiThread(()->{audioPlayed=true;message="Якщо звук чутно, торкнись «Чутно ✓».";event("audio","left440Hz/right660Hz");});
            }catch(Exception e){String error=e.toString();runOnUiThread(()->{message=error;event("audio_error",error);});}
            finally {if(track!=null){track.stop();track.release();}runOnUiThread(()->{busy=false;display.invalidate();});}
        },"classic-audio-test").start();
    }

    void vibrate() {
        try {
            android.view.InputDevice pad=android.view.InputDevice.getDevice(controllerId);
            Vibrator v=pad!=null?pad.getVibrator():(Vibrator)getSystemService(VIBRATOR_SERVICE);
            vibrationRoute=pad!=null?"virtual_gamepad_ff":"built_in";
            if(v!=null && v.hasVibrator()) {
                v.vibrate(VibrationEffect.createWaveform(new long[]{0,250,150,250},-1));
                vibrationSent=true;event("vibration",vibrationRoute+":two250ms");
            } else {message="Для цього контролера вібрація недоступна";event("vibration_error",vibrationRoute+":no vibrator");}
        } catch(Exception error){message=error.toString();event("vibration_error",message);}
    }

    final class TestView extends View {
        final Paint p=new Paint(3);
        TestView(){super(MainActivity.this);setFocusable(true);requestFocus();}
        void text(Canvas c,String s,float x,float y,float size,int color){p.setColor(color);p.setTextSize(size);p.setTextAlign(Paint.Align.CENTER);c.drawText(s,x,y,p);}
        void box(Canvas c,float l,float t,float r,float b,int color){p.setColor(color);c.drawRoundRect(l,t,r,b,12,12,p);}
        protected void onDraw(Canvas c) {
            float w=getWidth(),h=getHeight(),unit=Math.min(w/1240f,h/1080f);c.drawColor(Color.rgb(14,23,37));
            int green=Color.rgb(66,220,140),gray=Color.rgb(57,71,90),white=Color.WHITE;
            text(c,"Classic — перевірка",w/2,80*unit,38*unit,white);
            text(c,message,w/2,140*unit,23*unit,white);
            int i=0,count=0;for(java.util.Map.Entry<String,Boolean> e:buttons.entrySet()){
                int col=i%7,row=i/7;float x=w*(col+.5f)/7, y=240*unit+row*115*unit;
                box(c,x-65*unit,y-45*unit,x+65*unit,y+25*unit,e.getValue()?green:gray);
                text(c,e.getKey(),x,y,30*unit,white);if(e.getValue())count++;i++;}
            text(c,"Кнопки: "+count+"/14     Кути: "+corner+"/4",w/2,460*unit,29*unit,white);
            float[] xs={32*unit,w-32*unit,w-32*unit,32*unit},ys={32*unit,32*unit,h-32*unit,h-32*unit};
            for(i=0;i<4;i++){p.setColor(i<corner?green:(i==corner?Color.YELLOW:gray));c.drawCircle(xs[i],ys[i],30*unit,p);text(c,""+(i+1),xs[i],ys[i]+9*unit,23*unit,Color.BLACK);}
            float top=h*.54f, bh=h*.11f;
            box(c,w*.15f,top,w*.48f,top+bh,gray);text(c,busy?"Відтворюється…":"Відтворити звук",w*.315f,top+bh*.62f,27*unit,white);
            box(c,w*.52f,top,w*.85f,top+bh,audioHeard?green:gray);text(c,"Чутно ✓",w*.685f,top+bh*.62f,27*unit,white);
            top+=bh*1.3f;
            box(c,w*.15f,top,w*.48f,top+bh,gray);text(c,"Увімкнути вібрацію",w*.315f,top+bh*.62f,27*unit,white);
            box(c,w*.52f,top,w*.85f,top+bh,vibrationFelt?green:gray);text(c,"Відчутно ✓",w*.685f,top+bh*.62f,27*unit,white);
            box(c,w*.30f,h*.87f,w*.70f,h*.95f,gray);text(c,"Готово — повернутися",w*.5f,h*.922f,27*unit,white);
        }
        public boolean onTouchEvent(MotionEvent e) {
            if(e.getAction()!=MotionEvent.ACTION_DOWN)return true;
            float x=e.getX(),y=e.getY(),w=getWidth(),h=getHeight(),unit=Math.min(w/1240f,h/1080f);
            event("touch",x+","+y);
            float[] xs={32*unit,w-32*unit,w-32*unit,32*unit},ys={32*unit,32*unit,h-32*unit,h-32*unit};
            if(corner<4 && Math.hypot(x-xs[corner],y-ys[corner])<80*unit){corner++;event("corner",String.valueOf(corner));return true;}
            float top=h*.54f,bh=h*.11f;
            if(y>=top && y<=top+bh){if(x>=w*.15f&&x<=w*.48f)sound();else if(x>=w*.52f&&x<=w*.85f&&audioPlayed){audioHeard=true;event("human_audio","heard");}}
            else if(y>=top+bh*1.3f && y<=top+bh*2.3f){
                if(x>=w*.15f&&x<=w*.48f){vibrate();}
                else if(x>=w*.52f&&x<=w*.85f&&vibrationSent){vibrationFelt=true;event("human_vibration","felt");}}
            else if(y>=h*.87f&&y<=h*.95f&&x>=w*.30f&&x<=w*.70f&&!busy){finished=true;event("finish","user");finish();}
            invalidate();return true;
        }
    }
}
