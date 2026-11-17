/* Exercise the actual repaired arm64 function under qemu, with bounded XDR
 * readers and allocator. The linker maps its original PLT call sites to mocks. */
typedef unsigned int u32;
typedef unsigned long long u64;
struct entry { u64 fileid; char *name; u64 cookie; struct entry *next; };
struct stream { const u32 *words; unsigned pos, count, used; struct entry nodes[8]; };
extern int decoder(struct stream *, struct entry *);
static unsigned char tls[64] __attribute__((aligned(16)));
void *memset(void *dst, int value, unsigned long bytes) {
    unsigned char *p=dst; for(unsigned long i=0;i<bytes;i++)p[i]=(unsigned char)value;return dst;
}
void *memcpy(void *dst, const void *src, unsigned long bytes) {
    unsigned char *p=dst;const unsigned char *q=src;for(unsigned long i=0;i<bytes;i++)p[i]=q[i];return dst;
}
int mock_uint64(struct stream *s, u64 *v) {
    if (s->pos + 2 > s->count) return 0;
    *v = ((u64)s->words[s->pos] << 32) | s->words[s->pos + 1]; s->pos += 2; return 1;
}
int mock_bool(struct stream *s, u32 *v) {
    if (s->pos == s->count) return 0;
    *v = s->words[s->pos++]; return *v <= 1;
}
int mock_string(struct stream *s, char **v, u32 max) {
    if (s->pos == s->count || s->words[s->pos] > 2 || max != ~0U) return 0;
    *v = (char *[]) {"alpha", "beta", "gamma"}[s->words[s->pos++]]; return 1;
}
int mock_pointer(struct stream *s, struct entry **v, u32 size, int (*proc)(struct stream *, struct entry *)) {
    u32 more;
    if (size != sizeof(**v) || !mock_bool(s, &more)) return 0;
    if (!more) { *v = 0; return 1; }
    if (s->used == 8) return 0;
    *v = &s->nodes[s->used++]; return proc(s, *v);
}
__attribute__((noreturn)) void finish(int code) {
    register long x0 __asm__("x0") = code;
    register long x8 __asm__("x8") = 93;
    __asm__ volatile("svc 0" : : "r"(x0), "r"(x8) : "memory");
    __builtin_unreachable();
}
void mock_stack_fail(void) { finish(99); }
void _start(void) {
    __asm__ volatile("msr tpidr_el0, %0" : : "r"(tls) : "memory");
    const u32 words[] = {0,11,0,0,101,1, 0,22,1,0,202,1, 0,33,2,0,303,0};
    struct stream s = { .words=words, .count=18 }; struct entry root = {0};
    if (!decoder(&s,&root) || s.pos != 18) finish(1);
    struct entry *e=&root;
    for (unsigned i=0;i<3;i++) {
        if (!e || e->fileid != 11*(i+1) || e->cookie != 101*(i+1) || e->name[0] != "abg"[i]) finish(2);
        e=e->next;
    }
    if(e)finish(3);
    for(unsigned n=0;n<18;n++) {
        struct stream truncated = { .words=words, .count=n }; struct entry r={0};
        if(decoder(&truncated,&r))finish(4);
    }
    struct stream one={.words=words,.count=6}; struct entry r={0};
    u32 single[]={0,11,0,0,101,0};one.words=single;
    if(!decoder(&one,&r) || r.next || one.pos!=6)finish(5);
    finish(0);
}
