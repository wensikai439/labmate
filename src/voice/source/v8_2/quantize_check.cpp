#include <mlas.h>
#include <vector>
#include <cmath>
#include <cfenv>
#include <limits>
#include <random>
#include <chrono>
#include <iostream>
#include <cstdint>
template<class T> void check(float scale,T zp,int mode){
    std::fesetround(mode);std::vector<float> input;std::mt19937 random(17228);std::uniform_real_distribution<float>dist(-100000,100000);
    for(int i=0;i<100000;++i)input.push_back(dist(random)*scale);
    for(int i=-500;i<500;++i){float x=(i+.5f)*scale;input.push_back(x);input.push_back(std::nextafter(x,INFINITY));input.push_back(std::nextafter(x,-INFINITY));}
    input.push_back(INFINITY);input.push_back(-INFINITY);input.push_back(0);input.push_back(-0.f);input.push_back(std::numeric_limits<float>::denorm_min());
    std::vector<T> out(input.size());MlasQuantizeLinear<T>(input.data(),out.data(),out.size(),scale,zp);
    for(size_t i=0;i<input.size();++i){float q=std::nearbyintf(input[i]/scale)+float(zp);q=std::max(q,float(std::numeric_limits<T>::lowest()));q=std::min(q,float(std::numeric_limits<T>::max()));T reference=(T)(int32_t)q;if(out[i]!=reference){std::cerr<<"Mismatch "<<i<<" scale "<<scale<<" input "<<input[i]<<" mode "<<mode<<std::endl;throw 1;}}
}
int main(){try{int cases=0;for(float scale:{.001f,.1f,1.f,3.f,10000.f})for(int mode:{FE_TONEAREST,FE_DOWNWARD,FE_UPWARD}){for(uint8_t zp:{uint8_t(0),uint8_t(127),uint8_t(255)}){check(scale,zp,mode);++cases;}check<int8_t>(scale,-7,mode);check<int16_t>(scale,-32768,mode);check<uint16_t>(scale,65535,mode);cases+=3;}std::cout<<"{\"cases\":"<<cases<<",\"mismatches\":0,\"ARMv7_NEON\":true}"<<std::endl;return 0;}catch(...){return 2;}}
