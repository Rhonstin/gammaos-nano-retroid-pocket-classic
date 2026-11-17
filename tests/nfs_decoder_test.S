.section .decoder,"ax"
.global decoder
decoder:
.incbin "decoder.bin"
.section .stub_uint64,"ax"
b mock_uint64
.section .stub_bool,"ax"
b mock_bool
.section .stub_pointer,"ax"
b mock_pointer
.section .stub_string,"ax"
b mock_string
.section .stub_canary,"ax"
b mock_stack_fail
