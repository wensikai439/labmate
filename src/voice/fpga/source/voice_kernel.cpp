
#include <stdint.h>
#include "voice_weights.h"
template<int LEVELS>
static uint8_t activate(int32_t acc,const int32_t *th,int8_t dir,uint8_t constant) {
  if (!dir) return constant;
  int lo=0,hi=LEVELS;
  while (lo<hi) { int mid=(lo+hi)/2; bool hit=dir>0?acc>=th[mid]:acc<=th[mid];
    if (hit) lo=mid+1; else hi=mid; }
  return (uint8_t)lo;
}
template<int IN,int OUT,int TI,int K,int S,int D,int PAD,int GROUPS,int TO,int LEVELS,int POOL,typename INPUT,typename OUTPUT,typename WEIGHT>
static void conv_pool(const INPUT *input,OUTPUT *output,const WEIGHT *weights,
 const int32_t th[OUT][LEVELS],const int8_t dir[OUT],const uint8_t constant[OUT]) {
  for (int oc=0;oc<OUT;++oc) for (int t=0;t<TO/POOL;++t) {
    uint8_t maximum=0;
    for (int phase=0;phase<POOL;++phase) {
      int32_t acc=0;
      const int channel_base=(oc/(OUT/GROUPS))*(IN/GROUPS);
      for (int ic=0;ic<IN/GROUPS;++ic) for (int k=0;k<K;++k) {
#ifdef SMARTBOX_HLS
#pragma HLS PIPELINE II=1
#endif
        int source=(t*POOL+phase)*S+k*D-PAD;
        if (source>=0 && source<TI)
          acc+=(int32_t)input[(channel_base+ic)*TI+source]*(int32_t)weights[(oc*(IN/GROUPS)+ic)*K+k];
      }
      uint8_t code=activate<LEVELS>(acc,th[oc],dir[oc],constant[oc]);
      if (code>maximum) maximum=code;
    }
    output[oc*(TO/POOL)+t]=maximum;
  }
}
template<int IN,int OUT,int LEVELS,typename INPUT,typename OUTPUT,typename WEIGHT>
static void dense(const INPUT *input,OUTPUT *output,const WEIGHT *weights,
 const int32_t th[OUT][LEVELS],const int8_t dir[OUT],const uint8_t constant[OUT]) {
  for (int oc=0;oc<OUT;++oc) {
    int32_t acc=0;
    for (int ic=0;ic<IN;++ic) {
#ifdef SMARTBOX_HLS
#pragma HLS PIPELINE II=1
#endif
      acc+=(int32_t)input[ic]*(int32_t)weights[oc*IN+ic];
    }
    output[oc]=activate<LEVELS>(acc,th[oc],dir[oc],constant[oc]);
  }
}
extern "C" void smartbox_voice(const int8_t *features,int32_t *logits) {
#ifdef SMARTBOX_HLS
#pragma HLS INTERFACE m_axi port=features offset=slave bundle=memory depth=10240 max_read_burst_length=64
#pragma HLS INTERFACE m_axi port=logits offset=slave bundle=memory depth=10 max_write_burst_length=16
#pragma HLS INTERFACE s_axilite port=features bundle=control
#pragma HLS INTERFACE s_axilite port=logits bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#endif
  int8_t input[40*VOICE_TIME];
  for (int i=0;i<40*VOICE_TIME;++i) input[i]=features[i];

  l0_act_t stage0[4096];
  conv_pool<40,32,256,9,1,1,4,1,256,15,2>(input,stage0,l0_weights,l0_threshold,l0_direction,l0_constant);
  l1_act_t stage1[3072];
  conv_pool<32,48,128,9,1,1,4,1,128,15,2>(stage0,stage1,l1_weights,l1_threshold,l1_direction,l1_constant);
  l2_act_t stage2[64];
  conv_pool<48,64,64,9,1,1,4,1,64,15,64>(stage1,stage2,l2_weights,l2_threshold,l2_direction,l2_constant);
  l3_act_t stage3[64];
  dense<64,64,15>(stage2,stage3,l3_weights,l3_threshold,l3_direction,l3_constant);
  for (int oc=0;oc<10;++oc) { int32_t acc=0;
    for (int ic=0;ic<64;++ic) acc+=(int32_t)stage3[ic]*(int32_t)l4_weights[oc*64+ic];
    logits[oc]=acc; }
}

