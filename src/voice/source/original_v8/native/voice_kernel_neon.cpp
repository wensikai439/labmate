// ARM PS inference optimization. The exported weights and quantization stay unchanged.
#include <stdint.h>
#include <limits.h>
#include <type_traits>
#include "voice_weights.h"
#if defined(__ARM_NEON) && !defined(SMARTBOX_DISABLE_NEON) && !defined(SMARTBOX_HLS)
#include <arm_neon.h>
#define SMARTBOX_NATIVE_NEON 1
#else
#define SMARTBOX_NATIVE_NEON 0
#endif

template<int LEVELS>
static uint8_t activate(int32_t acc,const int32_t *th,int8_t dir,uint8_t constant) {
  if (!dir) return constant;
  int lo=0,hi=LEVELS;
  while (lo<hi) {
    const int mid=(lo+hi)/2;
    const bool hit=dir>0 ? acc>=th[mid] : acc<=th[mid];
    if (hit) lo=mid+1; else hi=mid;
  }
  return (uint8_t)lo;
}

#if SMARTBOX_NATIVE_NEON
template<typename INPUT>
static inline int16x8_t widen8(const INPUT *p) {
  static_assert(sizeof(INPUT)==1,"byte input required");
  const uint8x8_t bytes=vld1_u8(reinterpret_cast<const uint8_t *>(p));
  if constexpr (std::is_signed<INPUT>::value) return vmovl_s8(vreinterpret_s8_u8(bytes));
  else return vreinterpretq_s16_u16(vmovl_u8(bytes));
}
#endif

template<int IN,typename INPUT,typename WEIGHT>
static int32_t dot(const INPUT *input,const WEIGHT *weight) {
  int32_t acc=0;
  int ic=0;
#if SMARTBOX_NATIVE_NEON
  if constexpr (sizeof(INPUT)==1 && sizeof(WEIGHT)==1 && std::is_signed<WEIGHT>::value) {
    int32x4_t lo=vdupq_n_s32(0),hi=vdupq_n_s32(0);
    for (;ic+8<=IN;ic+=8) {
      const int16x8_t x=widen8(input+ic),w=widen8(weight+ic);
      lo=vmlal_s16(lo,vget_low_s16(x),vget_low_s16(w));
      hi=vmlal_s16(hi,vget_high_s16(x),vget_high_s16(w));
    }
    const int32x4_t total=vaddq_s32(lo,hi);
    const int32x2_t pair=vpadd_s32(vget_low_s32(total),vget_high_s32(total));
    const int32x2_t sum=vpadd_s32(pair,pair);
    acc=vget_lane_s32(sum,0);
  }
#endif
  for (;ic<IN;++ic) acc+=(int32_t)input[ic]*(int32_t)weight[ic];
  return acc;
}

template<int IN,int OUT,int TI,int K,int S,int D,int PAD,int GROUPS,int TO,int LEVELS,int POOL,typename INPUT,typename OUTPUT,typename WEIGHT>
static void conv_pool(const INPUT *input,OUTPUT *output,const WEIGHT *weights,
 const int32_t th[OUT][LEVELS],const int8_t dir[OUT],const uint8_t constant[OUT]) {
  static_assert(IN%GROUPS==0 && OUT%GROUPS==0 && TO%POOL==0,"invalid tensor dimensions");
#if SMARTBOX_NATIVE_NEON
  if constexpr (S==1 && D==1 && TO==TI && TO%8==0 && K<=2*PAD+1 && sizeof(INPUT)==1 && sizeof(WEIGHT)==1) {
    // Channel-major padding removes inner-loop bounds checks. Keep signed byte values intact.
    alignas(16) INPUT padded[IN*(TI+2*PAD)]={};
    for (int ic=0;ic<IN;++ic)
      for (int t=0;t<TI;++t) padded[ic*(TI+2*PAD)+PAD+t]=input[ic*TI+t];
    for (int oc=0;oc<OUT;++oc) {
      if (!dir[oc]) {
        for (int t=0;t<TO/POOL;++t) output[oc*(TO/POOL)+t]=constant[oc];
        continue;
      }
      alignas(16) int32_t accumulators[TO];
      const int channel_base=(oc/(OUT/GROUPS))*(IN/GROUPS);
      for (int t=0;t<TO;t+=8) {
        int32x4_t lo=vdupq_n_s32(0),hi=vdupq_n_s32(0);
        for (int ic=0;ic<IN/GROUPS;++ic) for (int k=0;k<K;++k) {
          const int16x8_t x=widen8(padded+(channel_base+ic)*(TI+2*PAD)+t+k);
          const int16_t w=(int16_t)weights[(oc*(IN/GROUPS)+ic)*K+k];
          lo=vmlal_n_s16(lo,vget_low_s16(x),w);
          hi=vmlal_n_s16(hi,vget_high_s16(x),w);
        }
        vst1q_s32(accumulators+t,lo);vst1q_s32(accumulators+t+4,hi);
      }
      // Max-pooling commutes with this monotone activation. Negative direction needs min.
      for (int t=0;t<TO/POOL;++t) {
        int32_t best=dir[oc]>0 ? INT32_MIN : INT32_MAX;
        for (int phase=0;phase<POOL;++phase) {
          const int32_t acc=accumulators[t*POOL+phase];
          if ((dir[oc]>0 && acc>best) || (dir[oc]<0 && acc<best)) best=acc;
        }
        output[oc*(TO/POOL)+t]=activate<LEVELS>(best,th[oc],dir[oc],constant[oc]);
      }
    }
    return;
  }
#endif
  // Portable fallback retains exact integer arithmetic and evaluates activation once per pool.
  for (int oc=0;oc<OUT;++oc) for (int t=0;t<TO/POOL;++t) {
    if (!dir[oc]) { output[oc*(TO/POOL)+t]=constant[oc];continue; }
    int32_t best=dir[oc]>0 ? INT32_MIN : INT32_MAX;
    const int channel_base=(oc/(OUT/GROUPS))*(IN/GROUPS);
    for (int phase=0;phase<POOL;++phase) {
      int32_t acc=0;
      for (int ic=0;ic<IN/GROUPS;++ic) for (int k=0;k<K;++k) {
        const int source=(t*POOL+phase)*S+k*D-PAD;
        if (source>=0 && source<TI)
          acc+=(int32_t)input[(channel_base+ic)*TI+source]*(int32_t)weights[(oc*(IN/GROUPS)+ic)*K+k];
      }
      if ((dir[oc]>0 && acc>best) || (dir[oc]<0 && acc<best)) best=acc;
    }
    output[oc*(TO/POOL)+t]=activate<LEVELS>(best,th[oc],dir[oc],constant[oc]);
  }
}

template<int IN,int OUT,int LEVELS,typename INPUT,typename OUTPUT,typename WEIGHT>
static void dense(const INPUT *input,OUTPUT *output,const WEIGHT *weights,
 const int32_t th[OUT][LEVELS],const int8_t dir[OUT],const uint8_t constant[OUT]) {
  for (int oc=0;oc<OUT;++oc) {
    if (!dir[oc]) output[oc]=constant[oc];
    else output[oc]=activate<LEVELS>(dot<IN>(input,weights+oc*IN),th[oc],dir[oc],constant[oc]);
  }
}
extern "C" void smartbox_voice(const int8_t *features,int32_t *logits) {
  l0_act_t stage0[4096];
  conv_pool<40,32,256,9,1,1,4,1,256,15,2>(features,stage0,l0_weights,l0_threshold,l0_direction,l0_constant);
  l1_act_t stage1[3072];
  conv_pool<32,48,128,9,1,1,4,1,128,15,2>(stage0,stage1,l1_weights,l1_threshold,l1_direction,l1_constant);
  l2_act_t stage2[64];
  conv_pool<48,64,64,9,1,1,4,1,64,15,64>(stage1,stage2,l2_weights,l2_threshold,l2_direction,l2_constant);
  l3_act_t stage3[64];
  dense<64,64,15>(stage2,stage3,l3_weights,l3_threshold,l3_direction,l3_constant);
  for (int oc=0;oc<10;++oc) logits[oc]=dot<64>(stage3,l4_weights+oc*64);
}