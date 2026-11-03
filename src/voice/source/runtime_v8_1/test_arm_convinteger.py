#!/usr/bin/env python3
"""Check patched ARM integer convolution against an exact int64 NumPy oracle."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
import numpy as np
import onnx
from onnx import helper,numpy_helper,TensorProto
root=Path(sys.argv[1]);build=root/'build';folder=build/'conv_smoke';folder.mkdir(exist_ok=True)
cpp=folder/'conv_check.cpp'
cpp.write_text(r'''
#include <onnxruntime_cxx_api.h>
#include <fstream>
#include <iostream>
#include <iterator>
#include <vector>
int main(int argc,char**argv){try{
  if(argc!=4)return 2;
  Ort::Env env(ORT_LOGGING_LEVEL_WARNING,"conv_check");Ort::SessionOptions options;
  options.SetIntraOpNumThreads(2);options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_BASIC);
  Ort::Session session(env,argv[1],options);
  std::ifstream input(argv[2],std::ios::binary),expected_file(argv[3],std::ios::binary);
  std::vector<uint8_t> data((std::istreambuf_iterator<char>(input)),{});
  std::vector<char> expected((std::istreambuf_iterator<char>(expected_file)),{});
  auto info=session.GetInputTypeInfo(0).GetTensorTypeAndShapeInfo();auto shape=info.GetShape();
  auto memory=Ort::MemoryInfo::CreateCpu(OrtArenaAllocator,OrtMemTypeDefault);
  auto tensor=Ort::Value::CreateTensor<uint8_t>(memory,data.data(),data.size(),shape.data(),shape.size());
  const char* names[]={"X"};const char* outputs[]={"Y"};
  auto result=session.Run(Ort::RunOptions{nullptr},names,&tensor,1,outputs,1);
  auto count=result[0].GetTensorTypeAndShapeInfo().GetElementCount();const auto* actual=result[0].GetTensorData<int32_t>();
  if(count*4!=expected.size())throw std::runtime_error("output size mismatch");
  for(size_t i=0;i<count;++i){int32_t want;memcpy(&want,expected.data()+4*i,4);if(want!=actual[i])throw std::runtime_error("integer arithmetic mismatch");}
  std::cout<<"passed "<<count<<" exact int32 outputs\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 2;}}
'''.replace('#include <fstream>','#include <fstream>\n#include <cstring>'))
cross=root/'tools/cross';env=os.environ.copy()
env['LD_LIBRARY_PATH']=str(cross/'usr/lib/x86_64-linux-gnu')+':'+env.get('LD_LIBRARY_PATH','')
archives=sorted((build/'ort_arm/Release').rglob('*.a'))
binary=folder/'conv_check_arm'
command=[str(cross/'usr/bin/arm-linux-gnueabihf-g++-13'),'-std=c++17','-O3','-pthread','-static','--sysroot='+str(cross),'-B'+str(cross/'usr/bin'),'-march=armv7-a','-mfpu=neon','-mfloat-abi=hard','-I'+str(root/'tools/headers'),str(cpp),'-Wl,--start-group']+list(map(str,archives))+['-Wl,--end-group','-ldl','-lm','-o',str(binary)]
subprocess.run(command,check=True,env=env)
rng=np.random.default_rng(20261022);results=[]
for index,(signed,channels,group,stride,pad,dilation,zx,zw,omit) in enumerate([
    (True,1,1,1,0,1,0,0,False), (True,4,1,2,1,1,128,-128,False),
    (True,4,2,1,2,2,255,127,False), (True,256,1,1,1,1,255,127,False),
    (True,2,1,1,1,1,0,0,True), (False,4,1,1,1,1,128,128,False),
    (False,4,2,2,1,1,255,0,False), (False,2,1,1,0,1,0,0,True)]):
    x=rng.integers(0,256,(1,channels,7,8),dtype=np.uint8)
    dtype=np.int8 if signed else np.uint8
    w=rng.integers(-128 if signed else 0,128 if signed else 256,(4,channels//group,3,3),dtype=dtype)
    initializers=[numpy_helper.from_array(w,'W')]
    names=['X','W']
    if not omit:
        initializers.extend([numpy_helper.from_array(np.array(zx,np.uint8),'xz'),numpy_helper.from_array(np.array(zw,dtype),'wz')]);names+=['xz','wz']
    else:zx=zw=0
    node=helper.make_node('ConvInteger',names,['Y'],pads=[pad]*4,strides=[stride]*2,dilations=[dilation]*2,group=group)
    graph=helper.make_graph([node],'exact_conv',[helper.make_tensor_value_info('X',TensorProto.UINT8,list(x.shape))],[helper.make_tensor_value_info('Y',TensorProto.INT32,[1,4,None,None])],initializers)
    model=helper.make_model(graph,opset_imports=[helper.make_opsetid('',13)],ir_version=8)
    onnx.checker.check_model(model);path=folder/f'case_{index}.onnx';onnx.save(model,path)
    centered=np.pad(x.astype(np.int64)-zx,((0,0),(0,0),(pad,pad),(pad,pad)),constant_values=0)
    wc=w.astype(np.int64)-zw;out_h=(7+2*pad-dilation*2-1)//stride+1;out_w=(8+2*pad-dilation*2-1)//stride+1
    want=np.zeros((1,4,out_h,out_w),np.int64)
    for m in range(4):
        channel_start=(m//(4//group))*(channels//group)
        for h in range(out_h):
            for v in range(out_w):
                patch=centered[0,channel_start:channel_start+channels//group,h*stride:h*stride+3*dilation:dilation,v*stride:v*stride+3*dilation:dilation]
                want[0,m,h,v]=np.sum(patch*wc[m],dtype=np.int64)
    inp=folder/f'case_{index}.input';out=folder/f'case_{index}.expected';inp.write_bytes(x.tobytes());out.write_bytes(want.astype('<i4').tobytes())
    run=subprocess.run([str(cross/'usr/bin/qemu-arm-static'),'-cpu','cortex-a9',str(binary),str(path),str(inp),str(out)],capture_output=True,text=True,timeout=90)
    result={'case':index,'signed_weights':signed,'group':group,'stride':stride,'padding':pad,'dilation':dilation,'channels':channels,'activation_zero_point':zx,'weight_zero_point':zw,'omitted_zero_points':omit,'max_abs_output':int(np.max(np.abs(want))),'exact_int32_passed':run.returncode==0,'stdout':run.stdout,'stderr':run.stderr}
    results.append(result);print(json.dumps(result),flush=True)
    if run.returncode:raise RuntimeError('ARM integer convolution failed')
report={'passed':True,'oracle':'Exact int64 centered convolution, compared to ARM int32 outputs','cases':results,'model_files_modified':False}
(root/'reports/arm_convinteger_tests.json').write_text(json.dumps(report,indent=2))
