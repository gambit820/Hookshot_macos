#version 450
// Sample the game's RGBA picture into a swapchain whose format a blit cannot take (MoltenVK: BGRA).
// The shader writes logical RGBA; the attachment stores the swapchain's order.
layout(set = 0, binding = 0) uniform sampler2D src;
layout(push_constant) uniform Push {
    vec2 src_origin;
    vec2 src_size;
    vec2 dst_origin;
    vec2 dst_size;
} pc;
layout(location = 0) out vec4 color;
void main() {
    vec2 local = (gl_FragCoord.xy - pc.dst_origin) / pc.dst_size;
    vec2 st = (pc.src_origin + local * pc.src_size) / vec2(textureSize(src, 0));
    color = texture(src, st);
}
