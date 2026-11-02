import { Color, type Texture, ShaderMaterial, Vector3 } from 'three'
import { PALETTE } from './levelColors'

/** Contour spacing in metres; every `MAJOR_EVERY`th line is drawn heavier. */
const CONTOUR_INTERVAL = 250
const MAJOR_EVERY = 4

const vertexShader = /* glsl */ `
  attribute float aElev;
  attribute float aEdge;
  attribute float aProm;
  attribute float aLand;
  varying float vElev;
  varying float vEdge;
  varying float vProm;
  varying float vLand;
  varying vec2 vUv;
  varying vec3 vNormal;

  void main() {
    vElev = aElev;
    vEdge = aEdge;
    vProm = aProm;
    vLand = aLand;
    vUv = uv;
    vNormal = normalize(normal);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const fragmentShader = /* glsl */ `
  uniform float uReveal;
  uniform float uFill;
  uniform float uMaxElev;
  uniform vec3 uInk;
  uniform vec3 uBlue;
  uniform vec3 uCyan;
  uniform vec3 uCloud;
  uniform vec3 uLight;
  uniform sampler2D uRiskMap;
  uniform sampler2D uClassMap;
  uniform float uRisk;
  varying float vElev;
  varying float vEdge;
  varying float vProm;
  varying float vLand;
  varying vec2 vUv;
  varying vec3 vNormal;

  const float INTERVAL = ${CONTOUR_INTERVAL.toFixed(1)};
  const float MAJOR = ${MAJOR_EVERY.toFixed(1)};

  // 1 on a contour line of the given spacing, antialiased by the screen-space gradient. Lines fade out where
  // they would be closer than a few pixels, so distant mountains do not turn into a solid wash.
  float contour(float elev, float interval, float widthPx) {
    float f = elev / interval;
    float g = fwidth(f);
    float w = max(g, 0.0009);
    float d = abs(fract(f - 0.5) - 0.5);
    float line = 1.0 - smoothstep(0.0, widthPx * w, d);
    return line * (1.0 - smoothstep(0.18, 0.42, g));
  }

  void main() {
    // The mesh is cut at the coast: sea samples of a coastal quad interpolate vLand toward 0.
    if (vLand < 0.5) discard;
    // Inland vLand is flat (fwidth 0), which would make smoothstep's edges equal; keep them apart.
    float coast = 1.0 - smoothstep(0.0, max(1.6 * fwidth(vLand), 0.02), vLand - 0.5);

    // Country class of the cell: 0 sea, 1 India, 2 Nepal, 3 Bhutan, 4 other land (drawn very dim).
    float cls = floor(texture2D(uClassMap, vUv).r * 255.0 + 0.5);
    float other = step(3.5, cls);

    // Reveal order: low ground first. sqrt spreads the plains and the Ghats before the Himalaya.
    float h = sqrt(clamp(vElev / uMaxElev, 0.0, 1.0));
    float behind = uReveal * 1.08 - h;               // > 0 once the front has passed
    float revealed = smoothstep(0.0, 0.02, behind);
    float front = exp(-pow(behind / 0.045, 2.0));    // bright band riding the reveal front

    float minor = contour(vElev, INTERVAL, 1.1);
    float major = contour(vElev, INTERVAL * MAJOR, 2.2);
    // Plains recede: low-relief ground keeps fewer lines, flatter light and a darker ramp.
    float mountain = vProm;
    float lines = max(minor * 0.55, major) * step(8.0, vElev) * mix(0.3, 1.0, mountain);
    lines *= mix(1.0, 0.18, other);

    // Shaded terrain: hypsometric ramp lit from the north-west, all mixes of the palette.
    float lambert = clamp(dot(normalize(vNormal), uLight), 0.0, 1.0);
    lambert = mix(0.55, lambert, mix(0.35, 1.0, mountain));
    vec3 low = mix(uInk, uBlue, 0.16);
    vec3 ramp = mix(low, mix(uInk, uBlue, 0.55), smoothstep(0.0, 0.45, h));
    ramp = mix(ramp, mix(uBlue, uCyan, 0.4), smoothstep(0.55, 1.0, h) * 0.6);
    ramp = mix(mix(uInk, ramp, 0.55), ramp, mountain);
    vec3 shaded = ramp * (0.42 + 1.05 * lambert);
    shaded += uCyan * pow(lambert, 6.0) * 0.06 * mountain;
    shaded = mix(shaded, uInk, 0.72 * other);

    vec3 lineCol = mix(uCyan, uCloud, clamp(front * 0.9 + major * 0.2, 0.0, 1.0));
    vec3 glow = lineCol * lines * revealed * (1.1 + 1.6 * front);
    glow *= mix(1.0, 0.2, uFill);

    vec3 col = uInk;
    col += glow;
    col += shaded * revealed * uFill;
    col += uCyan * front * 0.04 * (1.0 - uFill);
    col += uCyan * coast * 0.38 * revealed;

    // Risk draped on the terrain: one texel per cell, straight alpha, opaque only where a cell was scored.
    vec4 risk = texture2D(uRiskMap, vUv);
    col = mix(col, risk.rgb, risk.a * uRisk * revealed);

    // Feather the window border into the background instead of ending in a hard cut.
    col = uInk + (col - uInk) * vEdge;

    gl_FragColor = vec4(col, 1.0);
    #include <colorspace_fragment>
  }
`

export interface TerrainMaterialOptions {
  maxElevation: number
  /** Risk heat map, one texel per terrain sample; an empty texture is used until a grid arrives. */
  riskMap: Texture
  /** Country class per terrain sample (red channel, `MASK` code), nearest filtered. */
  classMap: Texture
}

export function createTerrainMaterial({ maxElevation, riskMap, classMap }: TerrainMaterialOptions): ShaderMaterial {
  return new ShaderMaterial({
    uniforms: {
      uReveal: { value: 0 },
      uFill: { value: 0 },
      uMaxElev: { value: Math.max(maxElevation, 1) },
      uRiskMap: { value: riskMap },
      uClassMap: { value: classMap },
      uRisk: { value: 0 },
      uInk: { value: new Color(PALETTE.ink) },
      uBlue: { value: new Color(PALETTE.blue) },
      uCyan: { value: new Color(PALETTE.cyan) },
      uCloud: { value: new Color(PALETTE.cloud) },
      uLight: { value: new Vector3(-0.55, 0.62, -0.5).normalize() },
    },
    vertexShader,
    fragmentShader,
  })
}
