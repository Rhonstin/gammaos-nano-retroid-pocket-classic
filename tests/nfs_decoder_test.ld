ENTRY(_start)
SECTIONS {
  . = 0x4cc18; .decoder : { *(.decoder) }
  . = 0x5d3d0; .stub_uint64 : { *(.stub_uint64) }
  . = 0x5d410; .stub_bool : { *(.stub_bool) }
  . = 0x5d420; .stub_pointer : { *(.stub_pointer) }
  . = 0x5d440; .stub_string : { *(.stub_string) }
  . = 0x5ebc0; .stub_canary : { *(.stub_canary) }
  . = 0x60000; .text : { *(.text*) }
  .rodata : { *(.rodata*) }
  .data : { *(.data*) }
  .bss : { *(.bss*) *(COMMON) }
  /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
