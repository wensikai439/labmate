// Standalone Linux voice intent entry: no Python, NumPy, or ONNX Runtime dependency.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "voice_weights.h"
#include "voice_frontend_constants.h"
#include "voice_policy.h"
extern "C" void smartbox_voice(const int8_t *, int32_t *);

static uint32_t le32(const uint8_t *p) { return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24); }
static unsigned le16(const uint8_t *p) { return p[0]|((unsigned)p[1]<<8); }
static void fail(const char *message) { fprintf(stderr,"%s\n",message); exit(2); }

static float *read_wav(const char *path, int *samples) {
    FILE *file = fopen(path,"rb");
    if (!file) fail("Cannot open WAV");
    uint8_t chunk[16];
    if (fread(chunk,1,12,file)!=12 || memcmp(chunk,"RIFF",4) || memcmp(chunk+8,"WAVE",4)) fail("Expected RIFF WAVE audio");
    bool format_ok = false;
    float *wave = NULL;
    while (fread(chunk,1,8,file)==8) {
        uint32_t bytes = le32(chunk+4);
        if (!memcmp(chunk,"fmt ",4)) {
            if (bytes<16 || fread(chunk,1,16,file)!=16) fail("Invalid WAV format chunk");
            format_ok = le16(chunk)==1 && le16(chunk+2)==1 && le32(chunk+4)==16000 && le16(chunk+14)==16;
            if (fseek(file,(long)(bytes-16+(bytes&1)),SEEK_CUR)) fail("Invalid WAV format size");
        } else if (!memcmp(chunk,"data",4)) {
            if (!format_ok || !bytes || bytes>384000 || (bytes&1)) fail("Use 16 kHz mono PCM16 WAV of at most 12 seconds");
            *samples = (int)(bytes/2);
            int padded = *samples<512 ? 512 : *samples;
            wave = (float *)calloc((size_t)padded,sizeof(float));
            if (!wave) fail("Not enough memory for WAV");
            for (int i=0;i<*samples;++i) {
                uint8_t pcm[2];
                if (fread(pcm,1,2,file)!=2) fail("Truncated WAV audio");
                wave[i]=(float)(int16_t)le16(pcm)/32768.f;
            }
            *samples=padded;
            break;
        } else if (bytes>0x7fffffffU || fseek(file,(long)(bytes+(bytes&1)),SEEK_CUR)) fail("Invalid WAV chunk size");
    }
    fclose(file);
    if (!wave) fail("WAV data chunk missing");
    return wave;
}

static void fft(float *real, float *imag) {
    for (int i=1,j=0;i<512;++i) {
        int bit=256;
        for (;j&bit;bit>>=1) j^=bit;
        j^=bit;
        if (i<j) { float t=real[i]; real[i]=real[j]; real[j]=t; t=imag[i]; imag[i]=imag[j]; imag[j]=t; }
    }
    for (int width=2;width<=512;width*=2) {
        float angle=-6.2831853071795864769f/width;
        float cr=cosf(angle), ci=sinf(angle);
        for (int start=0;start<512;start+=width) {
            float wr=1,wi=0;
            for (int j=0;j<width/2;++j) {
                int a=start+j,b=a+width/2;
                float br=real[b]*wr-imag[b]*wi, bi=real[b]*wi+imag[b]*wr;
                real[b]=real[a]-br; imag[b]=imag[a]-bi; real[a]+=br; imag[a]+=bi;
                float next=wr*cr-wi*ci; wi=wr*ci+wi*cr; wr=next;
            }
        }
    }
}

static void frontend(const float *wave,int samples,int8_t *output) {
    int frames=1+(samples-512)/160;
    float *mel=(float *)malloc((size_t)frames*40*sizeof(float));
    if (!mel) fail("Not enough memory for acoustic frontend");
    double smooth[40]={0};
    for (int t=0;t<frames;++t) {
        float real[512],imag[512]={0};
        for (int n=0;n<512;++n) real[n]=wave[t*160+n]*VOICE_WINDOW[n];
        fft(real,imag);
        float power[257];
        for (int k=0;k<257;++k) power[k]=real[k]*real[k]+imag[k]*imag[k];
        for (int f=0;f<40;++f) {
            float energy=0;
            for (int k=0;k<257;++k) energy+=power[k]*VOICE_MEL[k][f];
#if VOICE_FRONTEND_PCEN
            smooth[f]=t==0 ? energy : .025*(double)energy+.975*smooth[f];
            mel[f*frames+t]=(float)(sqrt((double)energy/(1e-6+smooth[f])+2.)-sqrt(2.));
#else
            float value=logf(fmaxf(energy,1e-10f));
            mel[f*frames+t]=fminf(fmaxf(value,-14.f),6.f);
#endif
        }
    }
    for (int f=0;f<40;++f) {
        float values[VOICE_TIME],mean=0,variance=0;
        for (int t=0;t<VOICE_TIME;++t) {
            float position=((float)t+.5f)*((float)frames/VOICE_TIME)-.5f;
            int lower=(int)floorf(position),upper=lower+1;
            float fraction=position-lower;
            lower=lower<0 ? 0 : lower>=frames ? frames-1 : lower;
            upper=upper<0 ? 0 : upper>=frames ? frames-1 : upper;
            values[t]=(VOICE_FRONTEND_PCEN ? (mel[f*frames+lower]*(1-fraction)+mel[f*frames+upper]*fraction) : (mel[f*frames+lower]*(1-fraction)+mel[f*frames+upper]*fraction+4.f)/10.f);
            mean+=values[t];
        }
        mean/=VOICE_TIME;
        for (int t=0;t<VOICE_TIME;++t) variance+=(values[t]-mean)*(values[t]-mean);
        float std=fmaxf(sqrtf(variance/VOICE_TIME),.05f);
        for (int t=0;t<VOICE_TIME;++t) {
            float code=nearbyintf((values[t]-mean)/std/3.f*128.f);
            output[f*VOICE_TIME+t]=(int8_t)fminf(fmaxf(code,-128.f),127.f);
        }
    }
    free(mel);
}

int main(int argc,char **argv) {
    if (argc!=2) { fprintf(stderr,"Usage: smartbox_voice /path/to/16k_mono_pcm16.wav\n"); return 2; }
    int samples=0;
    float *wave=read_wav(argv[1],&samples);
    int8_t features[40*VOICE_TIME];
    frontend(wave,samples,features);
    free(wave);
    int32_t logits[VOICE_CLASSES];
    smartbox_voice(features,logits);
    int best=0;
    for (int i=1;i<VOICE_CLASSES;++i) if (logits[i]>logits[best]) best=i;
    double denominator=0;
    for (int i=0;i<VOICE_CLASSES;++i) denominator+=exp(((double)logits[i]-logits[best])*VOICE_LOGIT_SCALE/VOICE_TEMPERATURE);
    double confidence=1/denominator;
    const char *proposal=confidence>=VOICE_INTENT_THRESHOLD[best] ? VOICE_LABELS[best] : "UNMATCHED";
    printf("{\"intent_proposal\":\"%s\",\"top_class\":\"%s\",\"score\":%.8f,\"score_is_calibrated\":%s,\"calibration_scope\":\"%s\",\"frequency_hz\":null,\"confirmation_required\":true,\"instrument_control_executed\":false,\"backend\":\"PS_integer_reference\"}\n",proposal,VOICE_LABELS[best],confidence,VOICE_POLICY_CALIBRATED ? "true" : "false",VOICE_CALIBRATION_SCOPE);
    return 0;
}
