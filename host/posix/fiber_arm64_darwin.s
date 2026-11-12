# Fiber switch for arm64 macOS. getcontext/swapcontext are not available here.
# x0 = void **save_sp, x1 = stack pointer to resume.
# Callee-saved registers only: the caller keeps the rest.
# The default arm64 ABI (not arm64e) does not authenticate LR, so a new fiber's
# saved LR can be the raw address of _hookshot_fiber_entry.

.section __TEXT,__text
.globl _hookshot_fiber_switch
.p2align 2
_hookshot_fiber_switch:
    stp x19, x20, [sp, #-16]!
    stp x21, x22, [sp, #-16]!
    stp x23, x24, [sp, #-16]!
    stp x25, x26, [sp, #-16]!
    stp x27, x28, [sp, #-16]!
    stp x29, x30, [sp, #-16]!
    stp d8, d9, [sp, #-16]!
    stp d10, d11, [sp, #-16]!
    stp d12, d13, [sp, #-16]!
    stp d14, d15, [sp, #-16]!
    mov x9, sp
    str x9, [x0]
    mov sp, x1
    ldp d14, d15, [sp], #16
    ldp d12, d13, [sp], #16
    ldp d10, d11, [sp], #16
    ldp d8, d9, [sp], #16
    ldp x29, x30, [sp], #16
    ldp x27, x28, [sp], #16
    ldp x25, x26, [sp], #16
    ldp x23, x24, [sp], #16
    ldp x21, x22, [sp], #16
    ldp x19, x20, [sp], #16
    ret

.globl _hookshot_fiber_entry
.p2align 2
_hookshot_fiber_entry:
    mov x0, x19
    bl _hookshot_fiber_start
    brk #1
