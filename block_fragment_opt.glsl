#version 120

/*  Zynq-7020 优化版: 去掉每像素的第二次纹理采样
 *
 *  原版最后两行是:
 *      vec3 sky_color = vec3(texture2D(sky_sampler, vec2(timer, fog_height)));
 *      color = mix(color, sky_color, fog_factor);
 *  也就是【每个像素都要再采一次天空纹理】算雾色。
 *  纯软件渲染 (llvmpipe) 下这是实打实的第二次采样, 代价很大。
 *  这里换成一个常量天蓝色 —— 雾只在远处可见, 视觉差别极小。
 */

uniform sampler2D sampler;
uniform sampler2D sky_sampler;
uniform float timer;
uniform float daylight;
uniform int ortho;

varying vec2 fragment_uv;
varying float fragment_ao;
varying float fragment_light;
varying float fog_factor;
varying float fog_height;
varying float diffuse;

const float pi = 3.14159265;

void main() {
    vec3 color = vec3(texture2D(sampler, fragment_uv));
    if (color == vec3(1.0, 0.0, 1.0)) {
        discard;
    }
    bool cloud = color == vec3(1.0, 1.0, 1.0);
    if (cloud && bool(ortho)) {
        discard;
    }
    float df = cloud ? 1.0 - diffuse * 0.2 : diffuse;
    float ao = cloud ? 1.0 - (1.0 - fragment_ao) * 0.2 : fragment_ao;
    ao = min(1.0, ao + fragment_light);
    df = min(1.0, df + fragment_light);
    float value = min(1.0, daylight + fragment_light);
    vec3 light_color = vec3(value * 0.3 + 0.2);
    vec3 ambient = vec3(value * 0.3 + 0.2);
    vec3 light = ambient + light_color * df;
    color = clamp(color * light * ao, vec3(0.0), vec3(1.0));

    /* ★ 优化点: 常量雾色, 不再做第二次纹理采样 */
    vec3 sky_color = vec3(0.58, 0.74, 0.94) * (daylight * 0.5 + 0.5);
    color = mix(color, sky_color, fog_factor);

    gl_FragColor = vec4(color, 1.0);
}
