#!/usr/bin/env python3
"""Add exact U8 x S8 support to the task-owned ORT 1.22 CPU kernel.

The trained ONNX files are untouched. A signed filter is represented internally
as w_u = w_s + 128 and z_u = z_s + 128. Every centered integer product is thus
identical, including quantized padding. Existing U8 x U8 execution is retained.
"""
import hashlib,json,subprocess,sys
from pathlib import Path
root=Path(sys.argv[1]);ort=root/'tools/onnxruntime'
path=ort/'onnxruntime/core/providers/cpu/quantization/conv_integer.cc'
original=path.read_text()
backup=root/'build/conv_integer.original.cc'
if not backup.exists():backup.write_text(original)
original=backup.read_text();text=original
replacements=[
('.TypeConstraint("T2", DataTypeImpl::GetTensorType<uint8_t>())',
 '.TypeConstraint("T2", std::vector<MLDataType>{DataTypeImpl::GetTensorType<uint8_t>(), DataTypeImpl::GetTensorType<int8_t>()})'),
('  uint8_t input_offset = 0;\n  uint8_t filter_offset = 0;',
 '  const bool signed_filter = W->IsDataType<int8_t>();\n  uint8_t input_offset = 0;\n  uint8_t filter_offset = signed_filter ? 128 : 0;'),
('    filter_offset = *(W_Zero_Point->Data<uint8_t>());',
 '    filter_offset = signed_filter\n        ? static_cast<uint8_t>(static_cast<int>(*W_Zero_Point->Data<int8_t>()) + 128)\n        : *W_Zero_Point->Data<uint8_t>();'),
('  const auto* Wdata = W->Data<uint8_t>();',
 '''  // Exact representation shift; no dequantization or rounding.
  std::vector<uint8_t> shifted_filter;
  const uint8_t* Wdata = nullptr;
  if (signed_filter) {
    const auto* source = W->Data<int8_t>();
    shifted_filter.resize(static_cast<size_t>(W->Shape().Size()));
    for (size_t i = 0; i < shifted_filter.size(); ++i) {
      shifted_filter[i] = static_cast<uint8_t>(static_cast<int>(source[i]) + 128);
    }
    Wdata = shifted_filter.data();
  } else {
    Wdata = W->Data<uint8_t>();
  }''')]
for old,new in replacements:
    assert text.count(old)==1,old
    text=text.replace(old,new)
path.write_text(text)
patch=subprocess.check_output(['git','-C',str(ort),'diff','--','onnxruntime/core/providers/cpu/quantization/conv_integer.cc'],text=True)
(root/'src/ort_convinteger_signed.patch').write_text(patch)
report={'patch':'ort_convinteger_signed.patch','original_sha256':hashlib.sha256(original.encode()).hexdigest(),
        'patched_sha256':hashlib.sha256(text.encode()).hexdigest(),'weights_changed':False,
        'arithmetic':'(w_s + 128) - (z_s + 128) == w_s - z_s; uint8 activation and exact int32 accumulation retained',
        'reason':'ORT 1.22 CPU registers ConvInteger U8xU8 only; the V8 model has signed convolution filters'}
(root/'reports/arm_convinteger_patch.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
