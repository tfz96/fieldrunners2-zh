/* Fieldrunners 2 build 37185: repair the dormant TrueType text path. */
typedef unsigned int u32;
typedef void (__attribute__((stdcall)) *GL0)(void);
typedef void (__attribute__((stdcall)) *GL3)(float,float,float);
typedef void (__attribute__((stdcall)) *GLColor)(unsigned char,unsigned char,unsigned char,unsigned char);
typedef struct { double x,y,z; } Point;
typedef float (__attribute__((thiscall)) *Advance)(void*,const char*,int,Point);
typedef void (__attribute__((thiscall)) *Render)(void*,void*);
typedef struct { void* font; float x,y,ox,oy,w,h,tracking,scale; char text[28]; u32 ha,va; unsigned char rgba[4]; } Text;
#include "metrics.h"
#include "fallback.h"
static const char* cached(const char*s,int*length) {
    unsigned a=2166136261u,b=5381u;
    for(int i=0;i<*length;i++){unsigned char c=s[i];a=(a^c)*16777619u;b=(b*33u)^c;}
    int lo=0,hi=sizeof(cached_maps)/sizeof(cached_maps[0]);
    while(lo<hi){int mid=(lo+hi)/2;if(cached_maps[mid].hash<a)lo=mid+1;else hi=mid;}
    for(int i=lo;i<(int)(sizeof(cached_maps)/sizeof(cached_maps[0]))&&cached_maps[i].hash==a;i++){
        if(cached_maps[i].check==b&&cached_maps[i].length==(unsigned)*length){
            s=cached_maps[i].zh;int n=0;while(s[n])n++;*length=n;break;
        }
    }
    return s;
}
static float glyph(unsigned cp) {
    int lo=0,hi=sizeof(metrics)/sizeof(metrics[0]);
    while(lo<hi){int mid=(lo+hi)/2;if(metrics[mid][0]<cp)lo=mid+1;else hi=mid;}
    return lo<(int)(sizeof(metrics)/sizeof(metrics[0]))&&metrics[lo][0]==cp?metrics[lo][1]*.001f:1.f;
}
static float width(const char*s,int n,float size) {
    float w=0;
    for(int i=0;i<n;) {
        unsigned char c=s[i++];unsigned cp=c;
        int tail=c<128?0:c<224?1:c<240?2:3;
        if(tail)cp=c&((1<<(6-tail))-1);
        while(tail--&&i<n)cp=(cp<<6)|((unsigned char)s[i++]&63);
        w+=glyph(cp)*size;
    }
    return w;
}
void __attribute__((stdcall)) render(Text*t) {
    const char*s=*(u32*)(t->text+24)<16?t->text+4:*(char**)(t->text+4);
    /* MSVC's string has a proxy at offset 0, data at 4, size at 20, capacity at 24. */
    int total=*(u32*)(t->text+20);
    if(!s||total<1||total>16384)return;
    s=cached(s,&total);
    /* Original bitmap fonts use braces as currency/star pictograms. */
    char normalized[1024];int used=0;
    for(int i=0;i<total;) {
        unsigned char c=s[i];int n=c<128?1:c<224?2:c<240?3:4;
        if(i+n>total||used+n>=1020)break;
        if(s[i]=='{'||s[i]=='}') {
            const char *symbol=s[i]=='{'?"\xe5\xb8\x81":"\xe2\x98\x85";
            for(int j=0;j<3;j++)normalized[used++]=symbol[j];
        } else for(int j=0;j<n;j++)normalized[used++]=s[i+j];
        i+=n;
    }
    normalized[used]=0;s=normalized;total=used;
    float size=60.f, scale=t->scale;
    if(!(scale>0.f&&scale<=20.f))return;
    int start[64],end[64],lines=0,a=0;
    float widths[64];
    int pass=0;
layout:
    lines=0;a=0;
    float limit=t->w>1.f?t->w/scale:10000.f;
    while(a<total&&lines<64){
        int e=a;float w=0;
        while(e<total&&s[e]!='\n'&&s[e]!='\r'){
            unsigned char c=s[e];int n=c<128?1:c<224?2:c<240?3:4;
            if(e+n>total)break;
            float v=width(s+e,n,size);
            if(w+v>limit&&e>a)break;
            w+=v;e+=n;
        }
        if(e==a&&s[e]!='\n'&&s[e]!='\r')e++;
        start[lines]=a;end[lines]=e;widths[lines]=w;lines++;
        a=e;while(a<total&&(s[a]=='\r'||s[a]=='\n')){char c=s[a++];if(c=='\n')break;}
    }
    if(t->h>1.f&&lines*size*1.16f*scale>t->h&&pass++<12){
        scale*=.90f;
        goto layout;
    }
    GL0 push=*(GL0*)0x102db4e4,pop=*(GL0*)0x102db500;
    GL3 translate=*(GL3*)0x102db4f0,scalef=*(GL3*)0x102db4fc;
    GLColor color=*(GLColor*)0x102db510;
    float height=lines*size*1.16f;
    float y=t->y;
    if(t->h>1.f)y+=t->h*.5f*(1.f-(float)t->va);
    y-=(1.f-(float)t->va*.5f)*height*scale;
    y+=size*.20f*scale;
    color(t->rgba[0],t->rgba[1],t->rgba[2],t->rgba[3]);
    for(int l=0;l<lines;l++){
        char buf[1024];int n=end[l]-start[l];if(n>1023)n=1023;
        for(int i=0;i<n;i++)buf[i]=s[start[l]+i];buf[n]=0;
        u32 str[7]={0,(u32)buf,0,0,0,(u32)n,1023};
        float x=t->x-widths[l]*scale*(float)t->ha*.5f;
        if(t->w>1.f)x+=t->w*.5f*(float)t->ha;
        push();translate(x,y+(lines-1-l)*size*1.16f*scale,0);scalef(scale,scale,1.f);
        ((Render)0x10193ef0)(t->font,str);
        pop();
    }
}
