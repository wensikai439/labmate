#!/usr/bin/env python3
"""Cache upstream-pinned archives using HTTP/1.1 and verify every SHA1."""
import concurrent.futures,hashlib,json,os,shutil,sys,time,urllib.request
from pathlib import Path
root=Path(sys.argv[1]);source=root/'tools/onnxruntime/cmake/deps.txt'
original=root/'src/ORT_deps.upstream.txt'
if not original.exists():shutil.copyfile(source,original)
needed={'abseil_cpp','date','eigen','flatbuffers','microsoft_gsl','onnx','protobuf','pytorch_cpuinfo','re2','safeint','google_nsync','nsync','nlohmann_json','json','boost_mp11'}
destination=root/'tools/downloads/deps';destination.mkdir(parents=True,exist_ok=True)
rows=[]
for line in original.read_text().splitlines():
    fields=line.split(';')
    if len(fields)==3 and fields[0] in needed:rows.append(fields)
def fetch(row):
    key,url,expected=row;target=destination/(key+'.zip')
    if target.exists() and hashlib.sha1(target.read_bytes()).hexdigest()==expected:return key,target
    # A codeload redirect is the same official archive; pinned content hash is
    # checked before it can enter the build.
    if 'github.com/' in url and '/archive/' in url:
        repo,ref=url.split('github.com/',1)[1].split('/archive/',1)
        if ref.startswith('refs/'):ref=ref.removesuffix('.zip')
        else:ref=ref.split('/')[0].removesuffix('.zip')
        url='https://codeload.github.com/'+repo+'/zip/'+ref
    for attempt in range(3):
        try:
            request=urllib.request.Request(url,headers={'User-Agent':'SmartBox-build/1.0'})
            temporary=target.with_suffix('.part')
            with urllib.request.urlopen(request,timeout=90) as incoming,temporary.open('wb') as output:
                shutil.copyfileobj(incoming,output,1024*1024)
            actual=hashlib.sha1(temporary.read_bytes()).hexdigest()
            if actual!=expected:raise RuntimeError(key+' upstream SHA1 mismatch: '+actual)
            os.replace(temporary,target);print(key,target.stat().st_size,'verified',flush=True);return key,target
        except Exception:
            if attempt==2:raise
            time.sleep(2)
with concurrent.futures.ThreadPoolExecutor(6) as pool:verified=dict(pool.map(fetch,rows))
rewritten=[]
for line in original.read_text().splitlines():
    fields=line.split(';')
    if fields[0] in verified:
        fields[1]=verified[fields[0]].as_uri();line=';'.join(fields)
    rewritten.append(line)
source.write_text('\n'.join(rewritten)+'\n')
(root/'reports/dependency_archive_hashes.json').write_text(json.dumps({key:{'path':str(path),'sha1':hashlib.sha1(path.read_bytes()).hexdigest()} for key,path in verified.items()},indent=2))
