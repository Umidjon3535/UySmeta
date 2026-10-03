/*
 * UySmeta — xona 3D modeli (three.js r128). Ikki ko'rinish:
 *   Room3D.dollhouse(...) — 3D sahifa: xona yuqoridan, aylantirib ko'riladi;
 *   Room3D.composite(...) — real ko'rinish: loyihadagi pol/devor/ship pardozi va mebellar foydalanuvchi yuklagan
 *                            rasmning o'z perspektivasida chiziladi (orqa devorning 4 burchagidan kamera hisoblanadi).
 * Ikkalasi bir xil joylashtirish va bir xil raqamlardan foydalanadi — narx ro'yxatidagi raqamlar bilan mos.
 */
(function () {
  "use strict";

  // ------------------------------------------------------------------ matematika
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const scale = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const norm = (a) => Math.hypot(a[0], a[1], a[2]);
  const unit = (a) => scale(a, 1 / norm(a));
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  function solveLinear(A, b) {
    const n = b.length, M = A.map((row, i) => [...row, b[i]]);
    for (let c = 0; c < n; c++) {
      let p = c;
      for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
      [M[c], M[p]] = [M[p], M[c]];
      for (let r = 0; r < n; r++) {
        if (r === c) continue;
        const k = M[r][c] / M[c][c];
        for (let j = c; j <= n; j++) M[r][j] -= k * M[c][j];
      }
    }
    return M.map((row, i) => row[n] / row[i]);
  }

  function homography(src, dst) {
    const A = [], b = [];
    for (let i = 0; i < 4; i++) {
      const [X, Y] = src[i], [u, v] = dst[i];
      A.push([X, Y, 1, 0, 0, 0, -u * X, -u * Y]); b.push(u);
      A.push([0, 0, 0, X, Y, 1, -v * X, -v * Y]); b.push(v);
    }
    const h = solveLinear(A, b);
    return [[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1]];
  }
  const column = (Hm, j, f) => [Hm[0][j] / f, Hm[1][j] / f, Hm[2][j]];

  /*
   * Orqa devorning rasmdagi 4 burchagi (0..1) va ship balandligidan kamera holati, devor kengligi va
   * deraza/eshiklarning devordagi o'rni. Fokus masofasi burchaklardan baholanadi, bo'lmasa — telefon kamerasi (~69°).
   */
  function solve(geometry, imgW, imgH, H, area) {
    const cx = imgW / 2, cy = imgH / 2, big = Math.max(imgW, imgH);
    const pts = geometry.back.map(([x, y]) => [x * imgW - cx, y * imgH - cy]);
    const len = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
    const plane = (W) => [[-W / 2, H], [W / 2, H], [W / 2, 0], [-W / 2, 0]];
    let W = clamp(H * (len(pts[0], pts[1]) + len(pts[3], pts[2])) / (len(pts[0], pts[3]) + len(pts[1], pts[2])), 1.2, 9);
    let Hm = homography(plane(W), pts);

    let f = 0.73 * big;
    const h31h32 = Hm[2][0] * Hm[2][1];
    if (Math.abs(h31h32) > 1e-12) {
      const f2 = -(Hm[0][0] * Hm[0][1] + Hm[1][0] * Hm[1][1]) / h31h32;
      if (f2 > 0 && Math.sqrt(f2) > 0.5 * big && Math.sqrt(f2) < 1.4 * big) f = Math.sqrt(f2);
    }
    // Devorning haqiqiy kengligi: ustunlar uzunligi nisbati (fokus ma'lum bo'lsa, perspektiva hisobga olinadi)
    for (let i = 0; i < 3; i++) {
      W = clamp(W * norm(column(Hm, 0, f)) / norm(column(Hm, 1, f)), 1.2, 9);
      Hm = homography(plane(W), pts);
    }
    const k1 = column(Hm, 0, f), k2 = column(Hm, 1, f), k3 = column(Hm, 2, f);
    let lam = 2 / (norm(k1) + norm(k2));
    if (k3[2] * lam < 0) lam = -lam;
    let r1 = unit(scale(k1, lam));
    let r2 = scale(k2, lam);
    r2 = unit(sub(r2, scale(r1, dot(r1, r2))));
    const r3 = cross(r1, r2), t = scale(k3, lam);
    const rows = [[r1[0], r2[0], r3[0]], [r1[1], r2[1], r3[1]], [r1[2], r2[2], r3[2]]];
    const C0 = [-dot(r1, t), -dot(r2, t), -dot(r3, t)];

    // Chuqurlik maydondan; kamera undan uzoqroqda tursa — pol, devor va ship kameragacha cho'ziladi (rasm chetida eski devor qolmasin)
    const roomD = clamp((area || W * 4) / W, 1.5, 12);
    const D = Math.max(roomD, C0[2] + 0.3);
    const C = [C0[0], C0[1], C0[2] - D / 2];  // xona markazi koordinatasiga: orqa devor z = -D/2
    const cam = { f, rows, C, imgW, imgH };

    const layout = { W, D, roomD, H, walls: ["back", "left", "right"], openings: [], cam, photo: true };
    for (const o of geometry.openings || []) {
      const [x1, y1, x2, y2] = o.box;
      const plane3 = o.wall === "back" ? ["z", -D / 2] : o.wall === "left" ? ["x", -W / 2] : ["x", W / 2];
      const hits = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]].map(([u, v]) => intersect(cam, u * imgW, v * imgH, plane3[0], plane3[1])).filter(Boolean);
      if (hits.length < 4) continue;
      const along = hits.map((p) => (o.wall === "back" ? p[0] : p[2])), ys = hits.map((p) => p[1]);
      const lim = o.wall === "back" ? W / 2 : D / 2;
      const t0 = clamp(Math.min(...along), -lim, lim), t1 = clamp(Math.max(...along), -lim, lim);
      if (t1 - t0 < 0.3) continue;
      layout.openings.push({ kind: o.kind, wall: o.wall, t0, t1, y0: o.kind === "door" ? 0 : clamp(Math.min(...ys), 0, H), y1: clamp(Math.max(...ys), 0.5, H), box: o.box });
    }
    // Yon devorlarning kadrga tushadigan qismi — mebel kamera orqasiga yoki kadr chetidan tashqariga qo'yilmasin
    const visibleUntil = (x) => {
      let last = -D / 2;
      for (let z = -D / 2; z <= D / 2; z += 0.05) {
        const a = project(cam, [x, 0, z]), b = project(cam, [x, 1.2, z]);
        if (!a || !b || a[0] < -0.02 || a[0] > 1.02 || a[1] > 1.02 || b[0] < -0.02 || b[0] > 1.02) break;
        last = z;
      }
      return last;
    };
    layout.lanes = { back: [-W / 2, W / 2], left: [-D / 2, visibleUntil(-W / 2) - 0.1], right: [-D / 2, visibleUntil(W / 2) - 0.1] };
    // Kadrdagi pol markazi — o'rtaga qo'yiladigan narsalar uchun
    let near = -D / 2;
    for (let z = -D / 2; z <= D / 2; z += 0.05) { const p = project(cam, [0, 0, z]); if (!p || p[1] > 0.97) break; near = z; }
    layout.center = { x: 0, z: (-D / 2 + near) / 2 };
    return layout;
  }

  function ray(cam, u, v) {
    const dx = (u - cam.imgW / 2) / cam.f, dy = (v - cam.imgH / 2) / cam.f;
    const [a1, a2, a3] = cam.rows;
    return [a1[0] * dx + a2[0] * dy + a3[0], a1[1] * dx + a2[1] * dy + a3[1], a1[2] * dx + a2[2] * dy + a3[2]];
  }
  function intersect(cam, u, v, axis, value) {
    const d = ray(cam, u, v), i = { x: 0, y: 1, z: 2 }[axis];
    if (Math.abs(d[i]) < 1e-9) return null;
    const s = (value - cam.C[i]) / d[i];
    return s > 0 ? [cam.C[0] + d[0] * s, cam.C[1] + d[1] * s, cam.C[2] + d[2] * s] : null;
  }
  // Dunyo nuqtasi -> rasmdagi joy (0..1); kamera orqasida bo'lsa null
  function project(cam, p) {
    const q = sub(p, cam.C), [a1, a2, a3] = cam.rows;
    const z = dot(a3, q);
    if (z <= 0.01) return null;
    return [(cam.f * dot(a1, q) / z + cam.imgW / 2) / cam.imgW, (cam.f * dot(a2, q) / z + cam.imgH / 2) / cam.imgH];
  }

  // Rasm geometriyasi bo'lmasa — kvadrat xona, derazalar orqa devorda, eshik chap devorda
  function defaultLayout(data) {
    const L = data.side, H = data.height, openings = [];
    for (let i = 0; i < data.windows; i++) {
      const c = -L / 2 + (L / (data.windows + 1)) * (i + 1);
      openings.push({ kind: "window", wall: "back", t0: c - 0.65, t1: c + 0.65, y0: 0.85, y1: 2.3 });
    }
    if (data.doors > 0) openings.push({ kind: "door", wall: "left", t0: L / 2 - 1.2, t1: L / 2 - 0.3, y0: 0, y1: 2.05 });
    return {
      W: L, D: L, H, walls: ["back", "left", "right", "front"], openings, photo: false,
      lanes: { back: [-L / 2, L / 2], left: [-L / 2, L / 2], right: [-L / 2, L / 2], front: [-L / 2, L / 2] },
      center: { x: 0, z: 0 },
    };
  }

  // ------------------------------------------------------------------ materiallar
  const col = (c) => new THREE.Color(c).convertSRGBToLinear();
  const tone = (c, k) => { const x = new THREE.Color(c); return k < 1 ? x.multiplyScalar(k) : x.lerp(new THREE.Color("#ffffff"), k - 1); };
  const hex = (c) => "#" + new THREE.Color(c).getHexString();
  const mat = (c, rough = 0.8, metal = 0, extra = {}) => new THREE.MeshStandardMaterial(Object.assign({ color: col(c), roughness: rough, metalness: metal }, extra));
  const WHITE = "#f4f4f2", METAL = "#b8bcc2", DARK = "#2a2a2e", WOOD = "#7a5c45";

  function box(w, h, d) {
    const r = Math.min(0.022, Math.min(w, h, d) * 0.3);
    return THREE.RoundedBoxGeometry && r > 0.004 ? new THREE.RoundedBoxGeometry(w, h, d, 2, r) : new THREE.BoxGeometry(w, h, d);
  }
  function B(g, w, h, d, x, y, z, m) {
    const mesh = new THREE.Mesh(box(w, h, d), m);
    mesh.position.set(x, y, z);
    mesh.castShadow = mesh.receiveShadow = true;
    g.add(mesh);
    return mesh;
  }
  function C(g, rt, rb, h, x, y, z, m, seg = 28) {
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), m);
    mesh.position.set(x, y, z);
    mesh.castShadow = mesh.receiveShadow = true;
    g.add(mesh);
    return mesh;
  }
  function texture(draw, size = 512) {
    const c = document.createElement("canvas");
    c.width = c.height = size;
    draw(c.getContext("2d"), size);
    const t = new THREE.CanvasTexture(c);
    t.encoding = THREE.sRGBEncoding;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.anisotropy = 4;
    return t;
  }
  const jitter = (c, amount) => hex(tone(c, 1 + (Math.random() - 0.5) * amount));

  const cache = {};
  const cached = (key, make) => cache[key] || (cache[key] = make());
  function fabricMap(c) {
    return cached("f" + c, () => {
      const t = texture((g, s) => {
        g.fillStyle = c; g.fillRect(0, 0, s, s);
        for (let y = 0; y < s; y += 2) { g.fillStyle = hex(tone(c, y % 4 ? 0.96 : 1.04)); g.fillRect(0, y, s, 1); }
        for (let x = 0; x < s; x += 3) { g.globalAlpha = 0.35; g.fillStyle = hex(tone(c, x % 6 ? 0.95 : 1.05)); g.fillRect(x, 0, 1, s); }
        g.globalAlpha = 1;
        for (let i = 0; i < 9000; i++) { g.fillStyle = jitter(c, 0.18); g.fillRect(Math.random() * s, Math.random() * s, 1, 1); }
      }, 256);
      t.repeat.set(3, 3);
      return t;
    });
  }
  function woodMap(c) {
    return cached("w" + c, () => {
      const t = texture((g, s) => {
        g.fillStyle = c; g.fillRect(0, 0, s, s);
        for (let i = 0; i < 140; i++) {
          g.strokeStyle = hex(tone(c, 0.78 + Math.random() * 0.3)); g.globalAlpha = 0.25 + Math.random() * 0.35;
          g.lineWidth = 0.6 + Math.random() * 2.2; g.beginPath();
          const x0 = Math.random() * s; g.moveTo(x0, 0);
          for (let y = 0; y <= s; y += 32) g.lineTo(x0 + Math.sin(y / 60 + i) * 6 + (Math.random() - 0.5) * 2, y);
          g.stroke();
        }
        g.globalAlpha = 1;
      });
      t.repeat.set(1, 1);
      return t;
    });
  }
  const fabric = (c) => new THREE.MeshStandardMaterial({ map: fabricMap(c), bumpMap: fabricMap(c), bumpScale: 0.0015, roughness: 1 });

  // Variant naqshi (styles.json): chiziqli, katakli, gulli, geometrik, ombre, damask ... — mato, oboi va gilam uchun
  function patternMap(pattern, c, c2, repeat = 3) {
    return cached(`p${pattern}${c}${c2}${repeat}`, () => {
      const t = texture((g, s) => {
        g.fillStyle = c; g.fillRect(0, 0, s, s);
        const a = c2 || hex(tone(c, 1.25));
        g.fillStyle = a; g.strokeStyle = a;
        if (pattern === "stripes") { g.globalAlpha = 0.55; for (let x = 0; x < s; x += s / 8) g.fillRect(x, 0, s / 22, s); }
        else if (pattern === "check") { g.globalAlpha = 0.28; for (let x = 0; x < s; x += s / 6) { g.fillRect(x, 0, s / 14, s); g.fillRect(0, x, s, s / 14); } }
        else if (pattern === "floral") {
          g.globalAlpha = 0.5;
          for (let i = 0; i < 18; i++) {
            const x = ((i * 97) % 13) / 13 * s, y = ((i * 53) % 11) / 11 * s, r = s / 26;
            for (let k = 0; k < 5; k++) { g.beginPath(); g.ellipse(x + Math.cos(k * 1.256) * r, y + Math.sin(k * 1.256) * r, r * 0.8, r * 0.45, k * 1.256, 0, Math.PI * 2); g.fill(); }
          }
        } else if (pattern === "geometric") {
          g.globalAlpha = 0.45; g.lineWidth = s / 90;
          for (let x = 0; x < s; x += s / 6) for (let y = 0; y < s; y += s / 6) { g.beginPath(); g.moveTo(x + s / 12, y); g.lineTo(x + s / 6, y + s / 12); g.lineTo(x + s / 12, y + s / 6); g.lineTo(x, y + s / 12); g.closePath(); g.stroke(); }
        } else if (pattern === "ombre") {
          const gr = g.createLinearGradient(0, 0, 0, s); gr.addColorStop(0, hex(tone(c, 1.35))); gr.addColorStop(1, c); g.fillStyle = gr; g.fillRect(0, 0, s, s);
        } else if (pattern === "damask") {
          g.globalAlpha = 0.4;
          for (let x = s / 8; x < s; x += s / 4) for (let y = s / 8; y < s; y += s / 4) {
            g.beginPath(); g.ellipse(x, y, s / 22, s / 12, 0, 0, Math.PI * 2); g.fill();
            g.beginPath(); g.ellipse(x - s / 16, y, s / 40, s / 22, 0.6, 0, Math.PI * 2); g.fill();
            g.beginPath(); g.ellipse(x + s / 16, y, s / 40, s / 22, -0.6, 0, Math.PI * 2); g.fill();
          }
        } else if (pattern === "concrete") {
          g.globalAlpha = 0.18; for (let i = 0; i < 2600; i++) { g.fillStyle = jitter(c, 0.5); g.fillRect(Math.random() * s, Math.random() * s, 3, 3); }
        } else if (pattern === "linen" || pattern === "texture") {
          g.globalAlpha = 0.16; for (let y = 0; y < s; y += 2) { g.fillStyle = hex(tone(c, y % 4 ? 0.9 : 1.1)); g.fillRect(0, y, s, 1); }
          for (let x = 0; x < s; x += 3) { g.fillStyle = hex(tone(c, 0.9)); g.fillRect(x, 0, 1, s); }
        }
        g.globalAlpha = 1;
        for (let i = 0; i < 5000; i++) { g.fillStyle = jitter(c, 0.12); g.globalAlpha = 0.25; g.fillRect(Math.random() * s, Math.random() * s, 1, 1); }
        g.globalAlpha = 1;
      }, 256);
      t.repeat.set(repeat, repeat);
      return t;
    });
  }
  // Mato turi: baxmal va atlas yaltiroqroq, zig'ir va bukle xira
  const ROUGH = { velvet: 0.62, satin: 0.32, linen: 1, cotton: 0.95, blackout: 0.85, velour: 0.7, rogojka: 1, chenille: 0.9, ecoleather: 0.45, leather: 0.38, boucle: 1 };
  function cloth(s, c, repeat = 3) {
    const map = s && s.pattern && s.pattern !== "plain" ? patternMap(s.pattern, c, s.color2, repeat) : fabricMap(c);
    return new THREE.MeshStandardMaterial({ map, bumpMap: fabricMap(c), bumpScale: s && s.fabric === "boucle" ? 0.004 : 0.0015, roughness: (s && ROUGH[s.fabric]) || 1 });
  }
  const METAL_TONE = { gold: "#c8a14a", black: "#1f1f22", chrome: "#c9ccd1", bronze: "#8a6a45", wood: WOOD };
  const wood = (c, rough = 0.5) => new THREE.MeshStandardMaterial({ map: woodMap(c), bumpMap: woodMap(c), bumpScale: 0.0008, roughness: rough });
  // Jigarrang-yog'och tusli rang — yog'och fakturasi bilan
  const woody = (c) => { const hsl = {}; new THREE.Color(c).getHSL(hsl); return hsl.h > 0.02 && hsl.h < 0.13 && hsl.s > 0.18 && hsl.l < 0.62; };
  const surface = (c, rough = 0.45) => (woody(c) ? wood(c, rough + 0.05) : mat(c, rough));

  // Burchak va mebel ostidagi yumshoq soya (ambient occlusion) — real fotoda doim bo'ladi
  const linearShade = () => cached("aoL", () => texture((g, s) => { const gr = g.createLinearGradient(0, 0, 0, s); gr.addColorStop(0, "#fff"); gr.addColorStop(1, "#000"); g.fillStyle = gr; g.fillRect(0, 0, s, s); }, 64));
  const radialShade = () => cached("aoR", () => texture((g, s) => { const gr = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2); gr.addColorStop(0, "#fff"); gr.addColorStop(0.55, "#999"); gr.addColorStop(1, "#000"); g.fillStyle = gr; g.fillRect(0, 0, s, s); }, 128));
  function shadePlane(w, h, map, opacity) {
    const m = new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity, alphaMap: map, depthWrite: false });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), m);
    mesh.renderOrder = 1;
    return mesh;
  }

  function floorMaterial(f, W, D) {
    const c = f.color, st = f.style || {};
    if (f.kind === "wood") {
      const rows = st.plank === "narrow" ? 11 : st.plank === "wide" ? 6 : 8;
      const t = texture((g, s) => {
        const plank = s / rows;
        for (let r = 0; r < rows; r++) {
          let x = -Math.random() * s * 0.5;
          while (x < s) {
            const len = s * (0.45 + Math.random() * 0.35);
            g.fillStyle = hex(tone(c, 0.9 + Math.random() * 0.2));
            g.fillRect(x, r * plank, len, plank);
            g.strokeStyle = hex(tone(c, 0.7)); g.lineWidth = 2; g.strokeRect(x, r * plank, len, plank);
            for (let k = 0; k < 6; k++) {
              g.strokeStyle = hex(tone(c, 0.85 + Math.random() * 0.1)); g.lineWidth = 1; g.beginPath();
              const yy = r * plank + Math.random() * plank; g.moveTo(x, yy); g.lineTo(x + len, yy + (Math.random() - 0.5) * 4); g.stroke();
            }
            x += len;
          }
        }
      });
      t.repeat.set(W / (st.plank === "long" ? 2.2 : 1.6), D / 1.6);
      return new THREE.MeshStandardMaterial({ map: t, bumpMap: t, bumpScale: st.finish === "textured" ? 0.003 : 0.001, roughness: st.finish === "satin" ? 0.3 : st.finish === "matte" ? 0.7 : 0.45, envMapIntensity: 0.45 });
    }
    if (f.kind === "tile60" || f.kind === "tile120") {
      const t = texture((g, s) => {
        g.fillStyle = hex(tone(c, 0.82)); g.fillRect(0, 0, s, s);
        for (let i = 0; i < 2; i++) for (let j = 0; j < 2; j++) {
          const x = i * s / 2 + 2, y = j * s / 2 + 2, ts = s / 2 - 4;
          g.fillStyle = jitter(c, 0.06); g.fillRect(x, y, ts, ts);
          if (st.look === "marble") {
            // Marmar tomirlari
            g.strokeStyle = hex(tone(c, 0.7)); g.globalAlpha = 0.35;
            for (let k = 0; k < 4; k++) { g.lineWidth = 0.5 + Math.random() * 1.5; g.beginPath(); g.moveTo(x, y + Math.random() * ts); g.bezierCurveTo(x + ts / 3, y + Math.random() * ts, x + ts * 0.6, y + Math.random() * ts, x + ts, y + Math.random() * ts); g.stroke(); }
            g.globalAlpha = 1;
          } else if (st.look === "concrete" || st.look === "stone") {
            g.globalAlpha = 0.2; for (let k = 0; k < 900; k++) { g.fillStyle = jitter(c, 0.4); g.fillRect(x + Math.random() * ts, y + Math.random() * ts, 2, 2); } g.globalAlpha = 1;
          } else if (st.look === "wood") {
            g.globalAlpha = 0.3; for (let k = 0; k < 10; k++) { g.fillStyle = hex(tone(c, 0.8 + Math.random() * 0.3)); g.fillRect(x, y + (ts / 10) * k, ts, 1.5); } g.globalAlpha = 1;
          }
        }
      });
      const tile = st.size === "120" ? 1.2 : st.size === "80" ? 0.8 : f.kind === "tile60" ? 0.6 : 1.2;  // teksturada 2×2 plitka
      t.repeat.set(W / (tile * 2), D / (tile * 2));
      return new THREE.MeshStandardMaterial({ map: t, roughness: st.finish === "matte" ? 0.65 : 0.22, envMapIntensity: 0.5 });
    }
    const t = texture((g, s) => { g.fillStyle = c; g.fillRect(0, 0, s, s); for (let i = 0; i < 4000; i++) { g.fillStyle = jitter(c, 0.15); g.fillRect(Math.random() * s, Math.random() * s, 2, 2); } });
    t.repeat.set(W / 2, D / 2);
    return new THREE.MeshStandardMaterial({ map: t, roughness: 0.95, envMapIntensity: 0.5 });
  }
  function wallMaterial(w, length, H) {
    const c = w.color, st = w.style || {};
    if (w.kind === "wallpaper" && st.pattern) {
      const t = patternMap(st.pattern, c, st.color2, 1);
      t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(length / 1.2, H / 1.2);
      return new THREE.MeshStandardMaterial({ map: t, roughness: 0.9, envMapIntensity: 0.6 });
    }
    if (w.kind === "paint" && st.finish === "satin") return mat(c, 0.6, 0, { envMapIntensity: 0.8 });
    if (w.kind === "wallpaper") {
      const t = texture((g, s) => {
        g.fillStyle = c; g.fillRect(0, 0, s, s);
        g.fillStyle = hex(tone(c, 0.93));
        for (let x = 0; x < s; x += s / 8) g.fillRect(x, 0, s / 32, s);
        g.fillStyle = hex(tone(c, 1.06));
        for (let x = s / 16; x < s; x += s / 4) for (let y = s / 16; y < s; y += s / 4) { g.beginPath(); g.arc(x, y, s / 40, 0, Math.PI * 2); g.fill(); }
      });
      t.repeat.set(length, H);
      return new THREE.MeshStandardMaterial({ map: t, roughness: 0.9, envMapIntensity: 0.6 });
    }
    if (w.kind === "tile") {
      const t = texture((g, s) => { g.fillStyle = hex(tone(c, 0.86)); g.fillRect(0, 0, s, s); for (let i = 0; i < 4; i++) for (let j = 0; j < 2; j++) { g.fillStyle = jitter(c, 0.03); g.fillRect(j * s / 2 + 1, i * s / 4 + 1, s / 2 - 2, s / 4 - 2); } });
      t.repeat.set(length / 0.6, H / 1.2);
      return new THREE.MeshStandardMaterial({ map: t, bumpMap: t, bumpScale: 0.002, roughness: 0.25, envMapIntensity: 0.6 });
    }
    return mat(c, 0.95, 0, { envMapIntensity: 0.6 });
  }

  // ------------------------------------------------------------------ mebel va texnika modellari
  // Kelib chiqishi — pol markazida; orqasi -z (devorga), oldi +z (xonaga)
  function sofa(g, w, d, h, c, arms = true, s = {}) {
    const body = cloth(s, c), light = cloth(s, hex(tone(c, 1.08))), leg = s.legs === "wood" ? wood(WOOD, 0.5) : mat(METAL_TONE[s.legs] || DARK, 0.35, s.legs === "gold" || s.legs === "chrome" ? 0.8 : 0.2);
    const arm = arms ? (s.arms === "thin" ? 0.08 : 0.16) : 0;
    const legH = s.legs === "hidden" ? 0.02 : s.legs ? 0.14 : 0.08;
    for (const [x, z] of [[-w / 2 + 0.08, -d / 2 + 0.08], [w / 2 - 0.08, -d / 2 + 0.08], [-w / 2 + 0.08, d / 2 - 0.08], [w / 2 - 0.08, d / 2 - 0.08]]) B(g, 0.04, legH, 0.04, x, legH / 2, z, leg);
    const lift = legH - 0.08;  // baland oyoqlarda butun divan ko'tariladi
    B(g, w, 0.24, d, 0, 0.2 + lift, 0, body);
    const n = w > 1.8 ? 3 : w > 1.2 ? 2 : 1, cw = (w - 2 * arm) / n;
    for (let i = 0; i < n; i++) {
      const x = -w / 2 + arm + cw * (i + 0.5);
      B(g, cw - 0.02, 0.13, d - 0.26, x, 0.385 + lift, 0.12, light);
      B(g, cw - 0.04, 0.38, 0.14, x, 0.62 + lift, -d / 2 + 0.29, light);
    }
    B(g, w, h - 0.08, 0.22, 0, 0.08 + lift + (h - 0.08) / 2, -d / 2 + 0.11, body);
    if (arms) for (const side of [-1, 1]) B(g, arm, s.arms === "thin" ? 0.45 : 0.55, d, side * (w / 2 - arm / 2), 0.355 + lift, 0, body);
  }
  function cornerSofa(g, w, d, h, c, s = {}) {
    const main = new THREE.Group(); sofa(main, w, 0.95, h, c, true, s); main.position.z = -d / 2 + 0.475; g.add(main);
    const ext = new THREE.Group(); sofa(ext, d - 0.95, 0.95, h, c, false, s); ext.rotation.y = Math.PI / 2; ext.position.set(-w / 2 + 0.475, 0, 0.475); g.add(ext);
  }
  function bed(g, w, d, h, c, s = {}) {
    const frameM = wood(s.frame || WOOD, 0.55);
    for (const [x, z] of [[-w / 2 + 0.06, -d / 2 + 0.06], [w / 2 - 0.06, -d / 2 + 0.06], [-w / 2 + 0.06, d / 2 - 0.06], [w / 2 - 0.06, d / 2 - 0.06]]) B(g, 0.06, 0.08, 0.06, x, 0.04, z, frameM);
    B(g, w, 0.26, d, 0, 0.21, 0, frameM);
    B(g, w - 0.06, 0.2, d - 0.08, 0, 0.44, 0.02, fabric("#f3f1ec"));
    B(g, w - 0.02, 0.05, d * 0.62, 0, 0.565, d * 0.19, fabric(c));
    const headM = s.head === "wood" ? frameM : cloth({ fabric: "velour" }, hex(tone(c, 0.85)));
    B(g, w + 0.1, 1.05, 0.09, 0, 0.525, -d / 2 + 0.045, headM);
    if (s.head === "tufted" || s.head === "vertical") {
      // Tikuvlar: kvadrat yoki tik chiziqlar
      const seam = mat(hex(tone(c, 0.62)), 0.9), cols = Math.round(w / 0.22);
      for (let i = 1; i < cols; i++) B(g, 0.012, s.head === "vertical" ? 0.9 : 0.012, 0.01, -w / 2 + (w / cols) * i, 0.6, -d / 2 + 0.093, seam);
      if (s.head === "tufted") for (let r = 0; r < 3; r++) B(g, w, 0.012, 0.01, 0, 0.3 + r * 0.25, -d / 2 + 0.093, seam);
    }
    const pillows = w < 1.2 ? 1 : 2;
    for (let i = 0; i < pillows; i++) B(g, w / pillows - 0.16, 0.12, 0.38, pillows === 1 ? 0 : (i ? 1 : -1) * w / 4, 0.6, -d / 2 + 0.33, fabric("#fbfbf8"));
  }
  function cabinet(g, w, d, h, c, opts = {}, s = {}) {
    const finish = (col_, rough) => (s.finish === "wood" ? wood(col_, rough) : s.finish === "gloss" ? mat(col_, 0.12, 0, { envMapIntensity: 1.2 }) : s.finish === "matte" ? mat(col_, 0.8) : surface(col_, rough));
    const body = finish(c, 0.5), front = finish(hex(tone(c, 1.04)), 0.35);
    const handle = mat(METAL_TONE[s.handle] || METAL, 0.25, s.handle === "black" ? 0.2 : 0.6);
    const noHandle = s.handle === "none";
    if (opts.legs) for (const x of [-w / 2 + 0.06, w / 2 - 0.06]) for (const z of [-d / 2 + 0.06, d / 2 - 0.06]) B(g, 0.04, 0.12, 0.04, x, 0.06, z, mat(DARK, 0.5));
    const base = opts.legs ? 0.12 : 0.06;
    if (!opts.legs) B(g, w - 0.04, base, d - 0.04, 0, base / 2, -0.02, mat(tone(c, 0.6), 0.7));
    const bh = h - base;
    B(g, w, bh, d, 0, base + bh / 2, 0, body);
    if (opts.doors) {
      const n = opts.doors, dw = w / n;
      for (let i = 0; i < n; i++) {
        const x = -w / 2 + dw * (i + 0.5);
        const panel = opts.mirror && i % 2 ? mat("#cfdde6", 0.12, 0.2) : front;
        B(g, dw - 0.01, bh - 0.02, 0.015, x, base + bh / 2, d / 2 + 0.008, panel);
        frontDetail(g, s.front, dw - 0.01, bh - 0.02, x, base + bh / 2, d / 2 + 0.016, c);
        if (opts.sliding) B(g, 0.02, bh - 0.02, 0.02, x + dw / 2 - 0.01, base + bh / 2, d / 2 + 0.02, mat(METAL, 0.3, 0.5));
        else if (!noHandle) B(g, 0.02, 0.18, 0.025, x + (i % 2 ? -1 : 1) * (dw / 2 - 0.06), base + bh * 0.55, d / 2 + 0.03, handle);
      }
    } else {
      const n = opts.drawers || 2, rh = bh / n;
      for (let i = 0; i < n; i++) {
        const y = base + rh * (i + 0.5);
        B(g, w - 0.03, rh - 0.02, 0.015, 0, y, d / 2 + 0.008, front);
        frontDetail(g, s.front, w - 0.03, rh - 0.02, 0, y, d / 2 + 0.016, c);
        if (!noHandle) B(g, Math.min(0.22, w * 0.3), 0.02, 0.025, 0, y + rh * 0.2, d / 2 + 0.03, handle);
      }
    }
  }
  // Fasad: frezerli (ramka) yoki reykali (tik reykalar)
  function frontDetail(g, kind, fw, fh, x, y, z, c) {
    if (kind === "milled") {
      const m = mat(hex(tone(c, 0.88)), 0.5), inset = Math.min(0.06, fw * 0.12);
      B(g, fw - 2 * inset, 0.008, 0.006, x, y + fh / 2 - inset, z, m); B(g, fw - 2 * inset, 0.008, 0.006, x, y - fh / 2 + inset, z, m);
      B(g, 0.008, fh - 2 * inset, 0.006, x - fw / 2 + inset, y, z, m); B(g, 0.008, fh - 2 * inset, 0.006, x + fw / 2 - inset, y, z, m);
    } else if (kind === "ribbed") {
      const m = mat(hex(tone(c, 0.82)), 0.6), n = Math.max(3, Math.round(fw / 0.035));
      for (let i = 1; i < n; i++) B(g, 0.006, fh - 0.02, 0.006, x - fw / 2 + (fw / n) * i, y, z, m);
    }
  }
  function shelf(g, w, d, h, c) {
    const m = surface(c, 0.5);
    for (const s of [-1, 1]) B(g, 0.03, h, d, s * (w / 2 - 0.015), h / 2, 0, m);
    B(g, w, h, 0.01, 0, h / 2, -d / 2 + 0.005, mat(tone(c, 0.9), 0.7));
    for (let i = 0; i <= 5; i++) {
      const y = 0.03 + (h - 0.06) * i / 5;
      B(g, w - 0.06, 0.025, d, 0, y, 0, m);
      if (i < 5 && i % 2 === 0) {
        let x = -w / 2 + 0.06;
        while (x < w / 2 - 0.15) {
          const bw = 0.03 + Math.random() * 0.03, bh = 0.18 + Math.random() * 0.08;
          B(g, bw, bh, d * 0.7, x + bw / 2, y + bh / 2 + 0.012, 0, mat(["#8c2f39", "#2f4b7c", "#d9b26f", "#3d5a40", "#555555"][Math.floor(Math.random() * 5)], 0.8));
          x += bw + 0.005;
        }
      }
    }
  }
  function table(g, w, d, h, c, chairs) {
    const m = surface(c, 0.4);
    B(g, w, 0.03, d, 0, h - 0.015, 0, m);
    B(g, w - 0.12, 0.06, d - 0.12, 0, h - 0.06, 0, m);
    for (const x of [-w / 2 + 0.08, w / 2 - 0.08]) for (const z of [-d / 2 + 0.08, d / 2 - 0.08]) C(g, 0.022, 0.016, h - 0.03, x, (h - 0.03) / 2, z, m, 12);
    if (!chairs) return;
    const seat = fabric("#c9c1b6"), frame = surface(hex(tone(c, 0.85)), 0.45);
    for (const side of [-1, 1]) for (const k of [-1, 1]) {
      const ch = new THREE.Group();
      B(ch, 0.44, 0.07, 0.44, 0, 0.46, 0, seat);
      for (const x of [-0.19, 0.19]) for (const z of [-0.19, 0.19]) C(ch, 0.016, 0.012, 0.43, x, 0.215, z, frame, 10);
      for (const x of [-0.19, 0.19]) C(ch, 0.014, 0.014, 0.42, x, 0.7, -0.2, frame, 10);
      B(ch, 0.42, 0.22, 0.04, 0, 0.8, -0.2, seat);
      ch.position.set(k * w / 4, 0, side * (d / 2 + 0.15));
      ch.rotation.y = side > 0 ? Math.PI : 0;
      g.add(ch);
    }
  }
  function kitchen(g, w, d, h, c) {
    const front = mat(c, 0.45), handle = mat(METAL, 0.25, 0.5);
    B(g, w, 0.1, d - 0.05, 0, 0.05, -0.025, mat(DARK, 0.6));
    B(g, w, 0.76, d - 0.02, 0, 0.48, 0, mat(tone(c, 0.95), 0.6));
    const n = Math.max(1, Math.round(w / 0.6)), dw = w / n;
    for (let i = 0; i < n; i++) {
      const x = -w / 2 + dw * (i + 0.5);
      B(g, dw - 0.01, 0.74, 0.015, x, 0.48, d / 2, front);
      B(g, dw * 0.5, 0.02, 0.025, x, 0.8, d / 2 + 0.02, handle);
      B(g, dw - 0.01, 0.7, 0.015, x, 1.85, -d / 2 + 0.36, front);
    }
    B(g, w + 0.02, 0.04, d + 0.02, 0, 0.88, 0.01, mat("#4a4a50", 0.3));
    B(g, w, 0.72, 0.34, 0, 1.85, -d / 2 + 0.17, mat(tone(c, 0.95), 0.6));
    B(g, w, 0.6, 0.01, 0, 1.2, -d / 2 + 0.005, mat("#e9e6df", 0.2));
    B(g, 0.5, 0.02, 0.4, w * 0.22, 0.895, 0, mat(METAL, 0.2, 0.5));
    C(g, 0.015, 0.015, 0.3, w * 0.22, 1.04, -d / 2 + 0.08, mat(METAL, 0.2, 0.5));
  }
  function officeChair(g, w, d, h, c) {
    const m = mat(DARK, 0.5);
    for (let i = 0; i < 5; i++) { const leg = B(g, 0.03, 0.03, 0.3, 0, 0.05, 0, m); leg.rotation.y = i * Math.PI * 2 / 5; leg.translateZ(0.15); }
    C(g, 0.025, 0.025, 0.38, 0, 0.25, 0, mat(METAL, 0.3, 0.5));
    B(g, 0.5, 0.08, 0.48, 0, 0.48, 0, mat(c, 0.9));
    B(g, 0.46, 0.55, 0.06, 0, 0.82, -0.22, mat(c, 0.9));
  }
  function tv(g, w, d, h) {
    B(g, w, h, 0.04, 0, h / 2, 0, mat("#111114", 0.2, 0.3));
    B(g, w - 0.03, h - 0.03, 0.005, 0, h / 2, 0.022, mat("#1b2130", 0.1, 0.2, { emissive: col("#0e1626"), emissiveIntensity: 0.4 }));
  }
  function fridge(g, w, d, h, c) {
    B(g, w, h, d, 0, h / 2, 0, mat(c, 0.35, 0.55));
    B(g, w, 0.01, 0.01, 0, h * 0.62, d / 2 + 0.005, mat(DARK, 0.5));
    for (const y of [h * 0.8, h * 0.45]) B(g, 0.025, 0.3, 0.03, w / 2 - 0.06, y, d / 2 + 0.02, mat(METAL, 0.2, 0.5));
  }
  function stove(g, w, d, h, c) {
    B(g, w, h - 0.02, d, 0, (h - 0.02) / 2, 0, mat(c, 0.4, 0.3));
    B(g, w, 0.02, d, 0, h - 0.01, 0, mat("#111111", 0.15));
    for (const x of [-w / 4, w / 4]) for (const z of [-d / 4, d / 4]) C(g, 0.06, 0.07, 0.025, x, h + 0.012, z, mat("#333333", 0.4, 0.5));
    B(g, w - 0.08, 0.35, 0.01, 0, 0.4, d / 2 + 0.005, mat("#1a1a1a", 0.1, 0.2));
  }
  function washer(g, w, d, h, c) {
    B(g, w, h, d, 0, h / 2, 0, mat(c, 0.35));
    const ring = C(g, 0.21, 0.21, 0.03, 0, h * 0.45, d / 2 + 0.01, mat(METAL, 0.25, 0.5)); ring.rotation.x = Math.PI / 2;
    const glass = C(g, 0.16, 0.16, 0.035, 0, h * 0.45, d / 2 + 0.012, mat("#2b3946", 0.05, 0.3)); glass.rotation.x = Math.PI / 2;
    B(g, w - 0.04, 0.08, 0.01, 0, h - 0.06, d / 2 + 0.005, mat("#d9dde2", 0.4));
  }
  function toilet(g, w, d, h, c) {
    const m = mat(c, 0.15);
    C(g, 0.14, 0.12, 0.38, 0, 0.19, 0.08, m);
    const bowl = C(g, 0.2, 0.16, 0.06, 0, 0.41, 0.1, m); bowl.scale.z = 1.3;
    B(g, 0.38, 0.38, 0.17, 0, 0.6, -d / 2 + 0.09, m);
  }
  function bathtub(g, w, d, h, c) {
    B(g, w, h, d, 0, h / 2, 0, mat(c, 0.15));
    B(g, w - 0.12, 0.01, d - 0.12, 0, h + 0.001, 0, mat("#cfe4ee", 0.05));
    C(g, 0.015, 0.015, 0.2, -w / 2 + 0.12, h + 0.1, -d / 2 + 0.05, mat(METAL, 0.2, 0.5));
  }
  function shower(g, w, d, h) {
    B(g, w, 0.12, d, 0, 0.06, 0, mat(WHITE, 0.2));
    const glass = mat("#d6ecf5", 0.05, 0, { transparent: true, opacity: 0.28 });
    B(g, w, h - 0.12, 0.01, 0, 0.12 + (h - 0.12) / 2, d / 2, glass);
    B(g, 0.01, h - 0.12, d, w / 2, 0.12 + (h - 0.12) / 2, 0, glass);
    C(g, 0.1, 0.1, 0.02, 0, h - 0.1, -d / 2 + 0.15, mat(METAL, 0.2, 0.5));
  }
  function mirror(g, w, d, h) {
    B(g, w + 0.04, h + 0.04, 0.02, 0, h / 2, 0, mat(DARK, 0.5));
    B(g, w, h, 0.01, 0, h / 2, 0.012, mat("#d4e3ec", 0.1, 0.2));
  }
  function rug(g, w, d, c, st = {}) {
    const c2 = st.color2 || hex(tone(c, 1.25));
    const t = texture((ctx, s) => {
      ctx.fillStyle = c; ctx.fillRect(0, 0, s, s);
      if (st.pattern && st.pattern !== "medallion") {
        ctx.fillStyle = c2; ctx.strokeStyle = c2;
        if (st.pattern === "stripes") for (let x = 0; x < s; x += s / 10) { ctx.globalAlpha = 0.6; ctx.fillRect(x, 0, s / 30, s); }
        else if (st.pattern === "geometric") { ctx.globalAlpha = 0.55; ctx.lineWidth = s / 70; for (let x = 0; x < s; x += s / 6) for (let y = 0; y < s; y += s / 6) { ctx.beginPath(); ctx.moveTo(x + s / 12, y + 4); ctx.lineTo(x + s / 6 - 4, y + s / 12); ctx.lineTo(x + s / 12, y + s / 6 - 4); ctx.lineTo(x + 4, y + s / 12); ctx.closePath(); ctx.stroke(); } }
        else if (st.pattern === "abstract") { ctx.globalAlpha = 0.5; for (let i = 0; i < 9; i++) { ctx.beginPath(); ctx.ellipse(((i * 71) % 10) / 10 * s, ((i * 37) % 9) / 9 * s, s / 7, s / 14, i, 0, Math.PI * 2); ctx.fill(); } }
        else if (st.pattern === "oriental" || st.pattern === "border") {
          ctx.globalAlpha = 0.85; ctx.lineWidth = s / 18; ctx.strokeRect(s / 16, s / 16, s - s / 8, s - s / 8);
          ctx.lineWidth = s / 80; ctx.strokeRect(s / 6, s / 6, s - s / 3, s - s / 3);
          if (st.pattern === "oriental") for (let x = s / 4; x < s * 0.8; x += s / 8) for (let y = s / 4; y < s * 0.8; y += s / 8) { ctx.beginPath(); ctx.arc(x, y, s / 50, 0, Math.PI * 2); ctx.fill(); }
        } else if (st.pattern === "plain") { ctx.globalAlpha = 0.2; for (let i = 0; i < 6000; i++) { ctx.fillStyle = jitter(c, 0.3); ctx.fillRect(Math.random() * s, Math.random() * s, 2, 2); } }
        ctx.globalAlpha = 1;
        return;
      }
      ctx.strokeStyle = hex(tone(c, 1.25)); ctx.lineWidth = s / 24; ctx.strokeRect(s / 12, s / 12, s - s / 6, s - s / 6);
      ctx.strokeStyle = hex(tone(c, 0.75)); ctx.lineWidth = s / 60; ctx.strokeRect(s / 6, s / 6, s - s / 3, s - s / 3);
      ctx.fillStyle = hex(tone(c, 1.2)); ctx.beginPath(); ctx.ellipse(s / 2, s / 2, s / 6, s / 9, 0, 0, Math.PI * 2); ctx.fill();
    });
    t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
    const m = B(g, w, 0.012, d, 0, 0.006, 0, new THREE.MeshStandardMaterial({ map: t, roughness: 1 }));
    m.castShadow = false;
  }
  function chandelier(g, w, d, h, c, s = {}) {
    const METAL = METAL_TONE[s.metal] || "#c9ccd1";
    C(g, 0.01, 0.01, h * 0.6, 0, h - h * 0.3, 0, mat(METAL, 0.3, 0.5));
    const glow = mat(c, 0.3, 0, { emissive: col("#ffe9b0"), emissiveIntensity: 0.9 });
    C(g, 0.06, 0.06, 0.05, 0, h * 0.35, 0, mat(METAL, 0.3, 0.5));
    for (let i = 0; i < 5; i++) {
      const a = i * Math.PI * 2 / 5, r = w / 2 - 0.08;
      const s = new THREE.Mesh(new THREE.SphereGeometry(0.065, 16, 12), glow);
      s.position.set(Math.cos(a) * r, h * 0.3, Math.sin(a) * r);
      g.add(s);
      const arm = B(g, r, 0.012, 0.012, Math.cos(a) * r / 2, h * 0.33, Math.sin(a) * r / 2, mat(METAL, 0.3, 0.5)); arm.rotation.y = -a;
    }
  }
  function floorLamp(g, w, d, h, c, s = {}) {
    const metal = mat(METAL_TONE[s.metal] || METAL, 0.3, s.metal === "black" ? 0.2 : 0.7);
    C(g, 0.14, 0.15, 0.03, 0, 0.015, 0, metal);
    C(g, 0.012, 0.012, h - 0.3, 0, (h - 0.3) / 2, 0, metal);
    C(g, 0.11, 0.17, 0.28, 0, h - 0.16, 0, mat(c, 0.8, 0, { emissive: col("#ffe9b0"), emissiveIntensity: 0.5 }));
  }
  function ac(g, w, d, h, c) {
    B(g, w, h, d, 0, h / 2, 0, mat(c, 0.35));
    B(g, w * 0.9, 0.025, 0.01, 0, 0.05, d / 2 + 0.002, mat("#9aa0a6", 0.5));
  }
  function hood(g, w, d, h, c) {
    B(g, w, 0.1, d, 0, 0.05, 0, mat(c, 0.25, 0.5));
    B(g, 0.26, h, 0.22, 0, 0.1 + h / 2, -d / 2 + 0.11, mat(c, 0.25, 0.5));
  }
  function boiler(g, w, d, h, c) { C(g, w / 2, w / 2, h, 0, h / 2, 0, mat(c, 0.3)); }

  const BUILDERS = {
    "divan": (g, w, d, h, c, s) => sofa(g, w, d, h, c, true, s),
    "kreslo": (g, w, d, h, c, s) => sofa(g, w, d, h, c, true, s),
    "burchak-divan": cornerSofa,
    "krovat": bed, "yotoqxona-toplam": bed, "bolalar-krovati": bed,
    "tumbochka": (g, w, d, h, c, s) => cabinet(g, w, d, h, c, { drawers: 2, legs: true }, s),
    "komod": (g, w, d, h, c, s) => cabinet(g, w, d, h, c, { drawers: 4 }, s),
    "tv-tumba": (g, w, d, h, c, s) => cabinet(g, w, d, h, c, { drawers: 1, legs: true }, s),
    "shkaf-kupe": (g, w, d, h, c, s) => cabinet(g, w, d, h, c, { doors: 2, sliding: true, mirror: true }, s),
    "dahliz-shkaf": (g, w, d, h, c, s) => cabinet(g, w, d, h, c, { doors: 2 }, s),
    "vanna-tumba": (g, w, d, h, c) => { cabinet(g, w, d, h - 0.04, c, { doors: 2 }); B(g, w, 0.04, d, 0, h - 0.02, 0, mat(WHITE, 0.15)); C(g, 0.015, 0.015, 0.18, 0, h + 0.09, -d / 2 + 0.06, mat(METAL, 0.2, 0.5)); },
    "stelaj": shelf,
    "jurnal-stoli": (g, w, d, h, c) => table(g, w, d, h, c, false),
    "ish-stoli": (g, w, d, h, c) => { table(g, w, d, h, c, false); const u = new THREE.Group(); cabinet(u, 0.4, d - 0.05, h - 0.06, c, { drawers: 3 }); u.position.x = w / 2 - 0.25; g.add(u); },
    "oshxona-stol": (g, w, d, h, c) => table(g, w, d, h, c, true),
    "ofis-kreslo": officeChair,
    "oshxona-ldsp": kitchen, "oshxona-mdf": kitchen, "oshxona-akril": kitchen,
    "tv-43": tv, "tv-55": tv,
    "muzlatgich-artel": fridge, "muzlatgich-samsung": fridge,
    "gaz-plita-artel": stove, "gaz-plita-gefest": stove,
    "kir-mashina-7": washer, "kir-mashina-10": washer,
    "unitaz": toilet, "vanna": bathtub, "dush-kabina": shower,
    "vanna-oyna": mirror, "dahliz-oyna": mirror,
    "konditsioner-12": ac, "konditsioner-18": ac,
    "vytyajka": hood, "boyler": boiler,
    "lyustra": chandelier, "torsher": floorLamp,
  };
  function model(o, w, d, h, opts = {}) {
    const g = new THREE.Group();
    if (opts.photos && o.img) {
      g.userData.board = photoBoard(g, o.img, w, h);
      return g;
    }
    const fn = BUILDERS[o.key];
    if (fn) fn(g, w, d, h, o.color, o.style || {});
    else B(g, w, h, d, 0, h / 2, 0, mat(o.color, 0.7));
    return g;
  }

  // ------------------------------------------------------------------ mahsulotning haqiqiy fotosi (real ko'rinish)
  /*
   * Hamkor mahsulotining foni olib tashlangan fotosi tik "doska" sifatida: pastki cheti polda, o'lchami mahsulotnikidek
   * (proporsiya fotodan). Rasm o'zi yoritilgan — sahna yorug'ligi va tone mapping unga ta'sir qilmaydi.
   */
  function photoTexture(img) {
    const tex = new THREE.Texture(img);
    tex.encoding = THREE.sRGBEncoding;
    tex.anisotropy = 4;
    tex.needsUpdate = true;
    return tex;
  }
  function photoBoard(g, img, w, h, fill = false) {
    const aspect = img.naturalWidth / img.naturalHeight || 1;
    let bw = h * aspect, bh = h;
    if (!fill && bw > w * 1.25) { bw = w * 1.25; bh = bw / aspect; }
    if (fill) { bw = w; bh = h; }
    const tex = photoTexture(img);
    const mesh = new THREE.Mesh(
      new THREE.PlaneGeometry(bw, bh),
      new THREE.MeshBasicMaterial({ map: tex, transparent: true, alphaTest: 0.04, side: THREE.DoubleSide, toneMapped: false })
    );
    mesh.position.y = bh / 2;
    mesh.castShadow = true;
    mesh.customDepthMaterial = new THREE.MeshDepthMaterial({ depthPacking: THREE.RGBADepthPacking, map: tex, alphaTest: 0.5 });
    g.add(mesh);
    return mesh;
  }

  // Sahna ma'lumotidagi "photo" manzillarini oldindan yuklaydi (composite sinxron chiziladi). Yuklanmasa — oddiy model.
  function loadPhotos(data) {
    const targets = [...(data.objects || []), data.parda, data.eshik].filter((o) => o && o.photo);
    return Promise.all(targets.map((o) => new Promise((resolve) => {
      const img = new Image();
      img.decoding = "async";
      img.onload = () => { o.img = img; resolve(); };
      img.onerror = () => resolve();
      img.src = o.photo;
    })));
  }

  // ------------------------------------------------------------------ xona va joylashtirish
  /*
   * finishes — pol, devor, ship pardozi (loyihada bo'lsa); furniture — mebel, texnika, eshik, parda, chiroqlar;
   * tags — har bir raqamli narsaning 3D'dagi joyi (raqam belgisi uchun).
   */
  function build(data, layout, opts = {}) {
    const { W, D, H } = layout;
    const finishes = new THREE.Group(), furniture = new THREE.Group(), tags = [];
    const tag = (n, x, y, z) => { if (n) tags.push({ n, p: new THREE.Vector3(x, y, z) }); };

    const frame = (wall, t, off) => {
      if (wall === "back") return { x: t, z: -D / 2 + off, rot: 0 };
      if (wall === "front") return { x: t, z: D / 2 - off, rot: Math.PI };
      if (wall === "left") return { x: -W / 2 + off, z: t, rot: Math.PI / 2 };
      return { x: W / 2 - off, z: t, rot: -Math.PI / 2 };
    };
    const forward = (rot) => [Math.sin(rot), Math.cos(rot)];
    const wallLength = (wall) => (wall === "back" || wall === "front" ? W : D);

    // Pardoz: 3D sahifada hammasi ko'rsatiladi, rasm ustida — faqat loyihada borlari (qolgani rasmdagidek qoladi)
    const show = (part) => !layout.photo || part.n;
    if (show(data.floor)) {
      const floor = new THREE.Mesh(new THREE.PlaneGeometry(W, D), floorMaterial(data.floor, W, D));
      floor.rotation.x = -Math.PI / 2;
      floor.receiveShadow = true;
      finishes.add(floor);
    }
    if (show(data.wall)) {
      for (const wall of layout.walls) {
        const len = wallLength(wall), f = frame(wall, 0, 0);
        const m = new THREE.Mesh(new THREE.PlaneGeometry(len, H), wallMaterial(data.wall, len, H));
        m.position.set(f.x, H / 2, f.z); m.rotation.y = f.rot; m.receiveShadow = true;
        finishes.add(m);
      }
    }
    if (show(data.ceiling)) {
      const ceiling = new THREE.Mesh(new THREE.PlaneGeometry(W, D), mat(data.ceiling.color, data.ceiling.n ? 0.15 : 0.9, data.ceiling.n ? 0.1 : 0));
      ceiling.rotation.x = Math.PI / 2;
      ceiling.position.y = H;
      finishes.add(ceiling);
    }
    if (data.plintus) {
      const pm = mat(data.plintus.color, 0.5);
      for (const wall of layout.walls) {
        const len = wallLength(wall), f = frame(wall, 0, 0.008), m = B(finishes, len, 0.07, 0.015, f.x, 0.035, f.z, pm);
        m.rotation.y = f.rot;
      }
      const f = frame("back", W / 2 - 0.4, 0.1);
      tag(data.plintus.n, f.x, 0.2, f.z);
    }
    // Devor-pol, devor-ship va devor-devor tutashgan joylardagi yumshoq soya
    if (show(data.floor) || show(data.wall)) {
      for (const wall of layout.walls) {
        const len = wallLength(wall), f = frame(wall, 0, 0);
        const onFloor = shadePlane(len, 0.45, linearShade(), 0.28);
        onFloor.rotation.order = "YXZ";
        onFloor.rotation.set(-Math.PI / 2, f.rot, 0);  // to'q tomoni devorga qaragan
        const [fx, fz] = forward(f.rot);
        onFloor.position.set(f.x + fx * 0.225, 0.003, f.z + fz * 0.225);
        finishes.add(onFloor);
        for (const [y, top, op] of [[0.2, false, 0.22], [H - 0.15, true, 0.18]]) {
          const strip = shadePlane(len, top ? 0.3 : 0.4, linearShade(), op);
          strip.position.set(f.x + fx * 0.003, y, f.z + fz * 0.003);
          strip.rotation.y = f.rot;
          if (!top) strip.rotation.z = Math.PI;  // to'q tomoni polga
          finishes.add(strip);
        }
      }
      // Orqa devor bilan yon devorlar tutashgan vertikal burchaklar (to'q tomoni burchakka)
      const corners = [["back", -W / 2 + 0.15, Math.PI / 2], ["back", W / 2 - 0.15, -Math.PI / 2], ["left", -D / 2 + 0.15, -Math.PI / 2], ["right", -D / 2 + 0.15, Math.PI / 2]];
      for (const [wall, t, rz] of corners) {
        if (!layout.walls.includes(wall)) continue;
        const f = frame(wall, t, 0.003), strip = shadePlane(H, 0.3, linearShade(), 0.16);
        strip.position.set(f.x, H / 2, f.z);
        strip.rotation.order = "YXZ"; strip.rotation.set(0, f.rot, rz);
        finishes.add(strip);
      }
    }
    tag(data.floor.n, layout.center.x + W * 0.22, 0.05, layout.center.z + 0.3);
    tag(data.wall.n, -W / 4, H * 0.8, -D / 2 + 0.05);
    tag(data.ceiling.n, W / 4, H - 0.05, layout.center.z - 0.3);

    // Derazalar va eshik (3D sahifada modeli chiziladi, rasm ustida — rasmdagi asli qoladi)
    let firstWindow = true;
    for (const o of layout.openings) {
      const w = o.t1 - o.t0, mid = (o.t0 + o.t1) / 2, h = o.y1 - o.y0, f = frame(o.wall, mid, 0);
      const g = new THREE.Group();
      g.position.set(f.x, 0, f.z); g.rotation.y = f.rot;
      if (o.kind === "window") {
        if (!layout.photo) {
          B(g, w + 0.1, h + 0.1, 0.06, 0, o.y0 + h / 2, 0.03, mat(WHITE, 0.5));
          B(g, w, h, 0.02, 0, o.y0 + h / 2, 0.07, mat("#bfe3f7", 0.05, 0.1, { emissive: col("#9fd3f5"), emissiveIntensity: 0.35 }));
          B(g, 0.04, h, 0.03, 0, o.y0 + h / 2, 0.08, mat(WHITE, 0.5));
          B(g, w + 0.2, 0.04, 0.2, 0, o.y0 - 0.02, 0.1, mat(WHITE, 0.5));
          finishes.add(g);
        }
        if (data.parda && opts.photos && data.parda.img) {
          // Haqiqiy parda fotosi deraza ustida: karnizdan polgacha, derazadan biroz keng
          const pg = new THREE.Group(); pg.position.copy(g.position); pg.rotation.y = g.rotation.y;
          const top = Math.min(H - 0.06, o.y1 + 0.3);
          const inner = new THREE.Group(); inner.position.z = 0.16; pg.add(inner);
          photoBoard(inner, data.parda.img, w + 0.7, top - 0.02, true);
          furniture.add(pg);
          if (firstWindow) { const tf = frame(o.wall, o.t0 - 0.3, 0.25); tag(data.parda.n, tf.x, top - 0.2, tf.z); }
        } else if (data.parda) {
          const pg = new THREE.Group(); pg.position.copy(g.position); pg.rotation.y = g.rotation.y;
          const st = data.parda.style || {}, type = st.type || "tulle";
          const top = Math.min(H - 0.06, o.y1 + 0.3), cm = cloth(st, data.parda.color, 2);
          if (type === "roman" || type === "roller") {
            // Rim / rulonli parda: deraza ustida, yuqori qismini yopadi
            const ph = (o.y1 - o.y0) * (type === "roman" ? 0.45 : 0.35), y = o.y1 - ph / 2;
            B(pg, w + 0.08, 0.06, 0.06, 0, o.y1 + 0.05, 0.1, type === "roller" ? mat(WHITE, 0.5) : cm);
            B(pg, w + 0.04, ph, 0.012, 0, y, 0.1, cm);
            if (type === "roman") for (let k = 1; k <= 3; k++) B(pg, w + 0.05, 0.03, 0.04, 0, o.y1 - (ph / 3.5) * k, 0.11, cm);
          } else {
            B(pg, w + 0.6, 0.03, 0.03, 0, top, 0.16, mat(METAL, 0.3, 0.5));
            for (const side of [-1, 1]) for (let k = 0; k < 5; k++) {
              const fold = B(pg, 0.09, top - 0.05, 0.03, side * (w / 2 + 0.05 + k * 0.08) * 0.92, top / 2, 0.18 + (k % 2) * 0.03, cm);
              fold.castShadow = false;
            }
            if (type === "tulle") B(pg, w + 0.2, top - 0.1, 0.01, 0, top / 2, 0.13, mat("#ffffff", 1, 0, { transparent: true, opacity: 0.35 }));
          }
          furniture.add(pg);
          if (firstWindow) { const tf = frame(o.wall, o.t0 - 0.3, 0.25); tag(data.parda.n, tf.x, top - 0.2, tf.z); }
        }
        firstWindow = false;
      } else if (data.eshik && opts.photos && data.eshik.img) {
        // Haqiqiy eshik fotosi eshik o'rnida
        const dw = Math.min(w, 0.95), dh = Math.min(h, 2.1);
        const inner = new THREE.Group(); inner.position.z = 0.04; g.add(inner);
        photoBoard(inner, data.eshik.img, dw + 0.12, dh + 0.07, true);
        furniture.add(g);
        tag(data.eshik.n, f.x, dh + 0.25, f.z);
      } else if (!layout.photo || data.eshik) {
        const dc = data.eshik ? data.eshik.color : "#9a8f84", dw = Math.min(w, 0.95), dh = Math.min(h, 2.1);
        const st = (data.eshik && data.eshik.style) || {}, kind = st.style || "panel2";
        const leaf = st.finish === "wood" ? wood(dc, 0.45) : st.finish === "paint" ? mat(dc, 0.5) : surface(dc, 0.45);
        const inset = st.finish === "wood" ? wood(hex(tone(dc, 0.94)), 0.45) : mat(hex(tone(dc, 0.94)), 0.5);
        const glass = mat("#cfe0ea", 0.08, 0.1, { transparent: true, opacity: 0.75 });
        B(g, dw + 0.12, dh + 0.07, 0.05, 0, (dh + 0.07) / 2, 0.025, kind === "loft" ? mat(DARK, 0.5) : mat(WHITE, 0.5));
        B(g, dw, dh, 0.04, 0, dh / 2, 0.06, leaf);
        if (kind === "panel2" || kind === "classic") {
          B(g, dw * 0.78, dh * 0.38, 0.01, 0, dh * 0.7, 0.085, inset);
          B(g, dw * 0.78, dh * 0.34, 0.01, 0, dh * 0.25, 0.085, inset);
          if (kind === "classic") for (const y of [dh * 0.7, dh * 0.25]) B(g, dw * 0.66, 0.012, 0.008, 0, y, 0.092, mat(hex(tone(dc, 0.8)), 0.5));
        } else if (kind === "panel4") {
          for (const x of [-dw * 0.21, dw * 0.21]) for (const y of [dh * 0.73, dh * 0.27]) B(g, dw * 0.34, dh * 0.36, 0.01, x, y, 0.085, inset);
        } else if (kind === "glass-strip") {
          B(g, dw * 0.12, dh * 0.82, 0.01, -dw * 0.22, dh * 0.5, 0.085, glass);
        } else if (kind === "glass-big") {
          B(g, dw * 0.7, dh * 0.6, 0.01, 0, dh * 0.6, 0.085, glass);
        } else if (kind === "loft") {
          B(g, dw * 0.86, dh * 0.86, 0.01, 0, dh * 0.5, 0.085, glass);
          for (let i = 1; i < 4; i++) B(g, 0.025, dh * 0.86, 0.012, -dw * 0.43 + dw * 0.86 * i / 4, dh * 0.5, 0.092, mat(DARK, 0.5));
          for (let i = 1; i < 6; i++) B(g, dw * 0.86, 0.025, 0.012, 0, dh * 0.07 + dh * 0.86 * i / 6, 0.092, mat(DARK, 0.5));
        } else if (kind === "grooves") {
          for (let i = 1; i < 8; i++) B(g, dw * 0.9, 0.008, 0.006, 0, dh * i / 8, 0.083, mat(hex(tone(dc, 0.82)), 0.5));
        }
        B(g, 0.12, 0.02, 0.04, dw / 2 - 0.12, 1.0, 0.1, mat(METAL_TONE[st.handle] || METAL, 0.25, st.handle === "black" ? 0.2 : 0.6));
        (data.eshik ? furniture : finishes).add(g);
        if (data.eshik) tag(data.eshik.n, f.x, dh + 0.25, f.z);
      }
    }

    // Nuqtali chiroqlar
    if (data.led_spot) {
      const n = data.led_spot.count, cols = Math.ceil(Math.sqrt(n)), rows = Math.ceil(n / cols);
      const lm = mat(data.led_spot.color, 0.3, 0, { emissive: col("#fff2c8"), emissiveIntensity: 1 });
      const z0 = -D / 2, z1 = layout.photo ? layout.center.z * 2 + D / 2 : D / 2;
      for (let i = 0; i < n; i++) {
        const x = -W / 2 + (W / (cols + 1)) * ((i % cols) + 1), z = z0 + ((z1 - z0) / (rows + 1)) * (Math.floor(i / cols) + 1);
        C(furniture, 0.05, 0.05, 0.01, x, H - 0.005, z, lm, 20).castShadow = false;
      }
      tag(data.led_spot.n, -W / 2 + W / (cols + 1), H - 0.15, z0 + (z1 - z0) / (rows + 1));
    }

    // Devor bo'ylab bo'sh joylar: eshik — har doim to'siq, deraza — baland narsalar uchun
    const used = { back: [], left: [], right: [], front: [] }, usedHigh = { back: [], left: [], right: [], front: [] };
    function fit(wall, need, tall, pool = used) {
      const [start, end] = layout.lanes[wall] || [0, -1];
      const blocks = pool[wall].concat(layout.openings.filter((o) => o.wall === wall && (o.kind === "door" || tall)).map((o) => [o.t0 - 0.1, o.t1 + 0.1]))
        .sort((a, b) => a[0] - b[0]);
      let cursor = start + 0.05;
      for (const [a, b] of blocks) {
        if (a - cursor >= need) break;
        cursor = Math.max(cursor, b);
      }
      if (cursor + need > end - 0.05) return null;
      pool[wall].push([cursor, cursor + need + 0.08]);
      return cursor;
    }
    function onWall(w, d, prefs, tall, extra = 0, pool = used) {
      for (const wall of prefs) {
        if (!layout.lanes[wall]) continue;
        const start = fit(wall, w + 2 * extra, tall, pool);
        if (start === null) continue;
        const t = start + extra + w / 2;
        return { f: frame(wall, t, d / 2 + 0.02), wall, t };
      }
      return null;
    }
    const centerSpots = [[0.15, 0.2], [-0.2, 0.25], [0.25, -0.1], [-0.25, -0.15]];
    let centerIndex = 0;
    const centerSpot = () => {
      const [a, b] = centerSpots[centerIndex++ % centerSpots.length];
      return { x: layout.center.x + a * W, z: layout.center.z + b * Math.min(D, 3), rot: 0 };
    };

    const keys = new Set(data.objects.map((o) => o.key));
    const rank = (o) => {
      if (/krovat|toplam|divan|oshxona-(ldsp|mdf|akril)|^vanna$/.test(o.key)) return 0;
      if (/shkaf|stelaj|muzlatgich|dush/.test(o.key)) return 1;
      return { wall: 2, high: 3, center: 4, floor: 5 }[o.place] ?? 6;
    };
    const placed = {};
    for (const o of data.objects.slice().sort((a, b) => rank(a) - rank(b))) {
      let [w, d, h] = o.size;
      w = Math.min(w, (o.place === "floor" ? Math.min(W, D) - 0.6 : W - 0.2));
      for (let copy = 0; copy < o.copies; copy++) {
        let g = model(o, w, d, h, opts), at = null, y = 0;
        const isBed = /krovat|toplam/.test(o.key);
        const tall = h > 0.95 || isBed || /^oshxona-(ldsp|mdf|akril)/.test(o.key);  // oshxonaning yuqori shkaflari bor
        if (o.place === "wall") {
          if (o.key === "tumbochka" && placed.bed && copy < 2) {
            const b = placed.bed;
            at = { f: frame(b.wall, b.t + (copy ? 1 : -1) * (b.w / 2 + 0.05 + w / 2), d / 2 + 0.02) };
          } else {
            const extra = isBed && keys.has("tumbochka") ? 0.55 : 0;
            const prefs = isBed ? ["back", "right", "left", "front"] : h > 1.1 ? ["left", "right", "front", "back"] : ["back", "right", "left", "front"];
            at = onWall(w, d, prefs, tall, extra);
            if (at && isBed) placed.bed = { wall: at.wall, t: at.t, w };
            if (at && /divan/.test(o.key) && !placed.sofa) placed.sofa = { ...at, d };
            if (at && o.key === "tv-tumba") placed.tvStand = { ...at, h };
            if (at && /plita/.test(o.key)) placed.stove = at;
            if (at && o.key === "vanna-tumba") placed.sinkStand = at;
            if (at && o.key === "ish-stoli") placed.desk = { ...at, d };
          }
        } else if (o.place === "high") {
          if (/^tv-/.test(o.key) && placed.tvStand) {
            const s = placed.tvStand;
            at = { f: frame(s.wall, s.t, 0.12) }; y = s.h + 0.04;
            const stand = new THREE.Group();
            B(stand, 0.3, 0.02, 0.2, 0, 0.01, 0, mat(DARK, 0.4)); B(stand, 0.05, 0.08, 0.03, 0, 0.05, -0.04, mat(DARK, 0.4));
            g.children.forEach((c) => { c.position.y += 0.08; });
            g.add(stand);
          } else if (o.key === "vytyajka" && placed.stove) {
            at = { f: frame(placed.stove.wall, placed.stove.t, d / 2 + 0.02) }; y = 1.6;
          } else if (o.key === "vanna-oyna" && placed.sinkStand) {
            at = { f: frame(placed.sinkStand.wall, placed.sinkStand.t, 0.03) }; y = 1.05;
          } else {
            // Konditsioner, ko'zgu, boyler — o'z balandligida, bir-birining va derazaning ustiga tushmasdan
            at = onWall(w, d, ["right", "left", "back"], true, 0, usedHigh);
            y = Math.min(o.elevation, H - h - 0.1);
          }
        } else if (o.place === "ceiling") {
          at = { f: { x: layout.center.x, z: layout.center.z, rot: 0 } }; y = H - h;
        } else if (o.place === "floor") {
          // Gilam — divan oldiga yoki krovat oldiga
          const rw = w, rd = Math.min(d, D - 0.8);
          g = new THREE.Group();
          if (opts.photos && o.img) {
            // Gilam fotosi (odatda yuqoridan olingan) — polda yotadi
            const m = new THREE.Mesh(new THREE.PlaneGeometry(rw, rd), new THREE.MeshStandardMaterial({ map: photoTexture(o.img), transparent: true, alphaTest: 0.04, roughness: 1 }));
            m.rotation.x = -Math.PI / 2; m.position.y = 0.006; m.receiveShadow = true;
            g.add(m);
          } else rug(g, rw, rd, o.color, o.style || {});
          if (placed.sofa) {
            const s = placed.sofa, [fx, fz] = forward(s.f.rot), off = s.d / 2 + rd / 2 + 0.1;
            at = { f: { x: s.f.x + fx * off, z: s.f.z + fz * off, rot: s.f.rot } };
          } else if (placed.bed) {
            const b = placed.bed, f = frame(b.wall, b.t, 1.7);
            at = { f: { x: f.x, z: f.z, rot: f.rot + Math.PI / 2 } };
          } else at = { f: { x: layout.center.x, z: layout.center.z, rot: 0 } };
        } else if (o.key === "jurnal-stoli" && placed.sofa) {
          const s = placed.sofa, [fx, fz] = forward(s.f.rot), off = s.d / 2 + 0.45 + d / 2;
          at = { f: { x: s.f.x + fx * off, z: s.f.z + fz * off, rot: s.f.rot } };
        } else if (o.key === "ofis-kreslo" && placed.desk) {
          const s = placed.desk, [fx, fz] = forward(s.f.rot), off = s.d / 2 + 0.3;
          at = { f: { x: s.f.x + fx * off, z: s.f.z + fz * off, rot: s.f.rot + Math.PI } };
        }
        if (!at) at = { f: centerSpot() };
        g.position.set(at.f.x, y, at.f.z);
        g.rotation.y = at.f.rot;
        if (g.userData.board && opts.camera) {
          // Foto kameraga qarab turadi (yon devordagi narsa ham "qirrasi" bilan ko'rinmasin)
          const [cx, , cz] = opts.camera;
          g.userData.board.rotation.y = Math.atan2(cx - at.f.x, cz - at.f.z) - at.f.rot;
        }
        furniture.add(g);
        if (o.place !== "high" && o.place !== "ceiling" && o.place !== "floor") {
          const blob = shadePlane(w * 1.25 + 0.2, d * 1.25 + 0.2, radialShade(), 0.5);
          blob.rotation.order = "YXZ"; blob.rotation.y = at.f.rot; blob.rotation.x = -Math.PI / 2;
          blob.position.set(at.f.x, 0.004, at.f.z);
          furniture.add(blob);
        }
        if (copy === 0) tag(o.n, at.f.x, o.place === "ceiling" ? H - h - 0.2 : y + h + 0.25, at.f.z);
      }
    }
    return { finishes, furniture, tags };
  }

  let envTexture = null;
  function environment(renderer) {
    if (!envTexture && THREE.RoomEnvironment) {
      const pmrem = new THREE.PMREMGenerator(renderer);
      envTexture = pmrem.fromScene(new THREE.RoomEnvironment(), 0.04).texture;
      pmrem.dispose();
    }
    return envTexture;
  }
  function setupRenderer(renderer) {
    renderer.outputEncoding = THREE.sRGBEncoding;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.8;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.VSMShadowMap;  // yumshoq soyalar
  }
  function lights(scene, layout, shadows, renderer) {
    const { W, D, H } = layout;
    const env = renderer && environment(renderer);
    if (env) { scene.environment = env; scene.add(new THREE.HemisphereLight(0xffffff, 0x8a7f72, 0.25)); }
    else { scene.add(new THREE.HemisphereLight(0xffffff, 0x8a7f72, 0.6)); scene.add(new THREE.AmbientLight(0xffffff, 0.2)); }
    // Kunduzgi yorug'lik deraza tomonidan kiradi (rasmdagidek); deraza bo'lmasa — yuqoridan
    const win = layout.openings.find((o) => o.kind === "window");
    const sun = new THREE.DirectionalLight(0xfff6ea, env ? 0.9 : 0.75);
    if (win) {
      const mid = (win.t0 + win.t1) / 2;
      const p = win.wall === "back" ? [mid, H * 3.2, -D / 2 - 2.5] : [win.wall === "left" ? -W / 2 - 2.5 : W / 2 + 2.5, H * 3.2, mid];
      sun.position.set(...p);
      sun.target.position.set(0, 0, layout.center.z + 0.5);
    } else sun.position.set(W * 0.6, H * 3, D * 1.2);
    scene.add(sun.target);
    if (shadows) {
      sun.castShadow = true;
      sun.shadow.mapSize.set(2048, 2048);
      const r = Math.max(W, D) * 1.2;
      Object.assign(sun.shadow.camera, { left: -r, right: r, top: r, bottom: -r, near: 0.1, far: H * 12 + D * 2 });
      sun.shadow.bias = -0.0004;
      sun.shadow.radius = 7;
    }
    scene.add(sun);
  }

  function tagSprite(n, accent) {
    const c = document.createElement("canvas");
    c.width = c.height = 64;
    const g = c.getContext("2d");
    g.fillStyle = accent; g.beginPath(); g.arc(32, 32, 28, 0, Math.PI * 2); g.fill();
    g.lineWidth = 4; g.strokeStyle = "#fff"; g.stroke();
    g.fillStyle = "#fff"; g.font = "bold 28px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText(String(n), 32, 34);
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false }));
    s.scale.set(0.3, 0.3, 1);
    s.renderOrder = 10;
    return s;
  }

  // ------------------------------------------------------------------ 3D sahifa
  /*
   * Rasm asosidagi joylashuvdan yopiq xona: haqiqiy chuqurlik (maydondan), old devor bilan. Rasm uchun pol kameragacha
   * cho'zilgan bo'lishi mumkin — orqa devor joyida qolishi uchun yon devordagi koordinatalar suriladi.
   */
  function closedRoom(layout) {
    const D = Math.min(layout.D, layout.roomD || layout.D), shift = (layout.D - D) / 2;
    const along = (wall, v) => (wall === "back" || wall === "front" ? v : Math.min(D / 2, v + shift));
    return Object.assign({}, layout, {
      D, photo: false, walls: ["back", "left", "right", "front"],
      openings: layout.openings.map((o) => Object.assign({}, o, { t0: along(o.wall, o.t0), t1: along(o.wall, o.t1) })).filter((o) => o.t1 - o.t0 > 0.3),
      lanes: {
        back: layout.lanes.back,
        left: [-D / 2, D / 2], right: [-D / 2, D / 2], front: [-layout.W / 2, layout.W / 2],
      },
      center: { x: 0, z: 0 },
    });
  }

  function dollhouse(box, data, layout, accent) {
    const { W, D, H } = layout;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(getComputedStyle(document.body).backgroundColor || "#f7f8fa");
    const camera = new THREE.PerspectiveCamera(42, box.clientWidth / box.clientHeight, 0.05, 100);
    const R = Math.max(W, D);
    camera.position.set(R * 0.75, H * 1.5, R * 0.95);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(box.clientWidth, box.clientHeight);
    setupRenderer(renderer);
    box.appendChild(renderer.domElement);
    const controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.target.set(0, H * 0.3, 0);
    controls.maxPolarAngle = Math.PI / 2.05;
    controls.enableDamping = true;
    controls.update();
    lights(scene, layout, true, renderer);

    const room = build(data, layout.photo ? closedRoom(layout) : layout);
    scene.add(room.finishes, room.furniture);
    for (const t of room.tags) { const s = tagSprite(t.n, accent); s.position.copy(t.p); scene.add(s); }

    window.addEventListener("resize", () => {
      camera.aspect = box.clientWidth / box.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(box.clientWidth, box.clientHeight);
    });
    (function loop() { controls.update(); renderer.render(scene, camera); requestAnimationFrame(loop); })();
  }

  // ------------------------------------------------------------------ real ko'rinish: rasm ustida
  let shared = null;  // bitta WebGL konteksti — burchaklarni surganda qayta-qayta yaratilmasin
  function composite(canvas, photo, data, layout) {
    const cam = layout.cam;
    const k = Math.min(1, 1600 / cam.imgW);
    const w = Math.round(cam.imgW * k), h = Math.round(cam.imgH * k);
    if (!shared) {
      shared = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
      setupRenderer(shared);
      shared.setClearColor(0x000000, 0);
    }
    const renderer = shared;
    renderer.setPixelRatio(1);
    renderer.setSize(w, h, false);

    const camera = new THREE.PerspectiveCamera(2 * Math.atan(cam.imgH / 2 / cam.f) * 180 / Math.PI, cam.imgW / cam.imgH, 0.05, 100);
    const [a1, a2, a3] = cam.rows;
    camera.matrixAutoUpdate = false;
    camera.matrix.makeBasis(new THREE.Vector3(...a1), new THREE.Vector3(-a2[0], -a2[1], -a2[2]), new THREE.Vector3(-a3[0], -a3[1], -a3[2]));
    camera.matrix.setPosition(new THREE.Vector3(...cam.C));
    camera.updateMatrixWorld(true);

    const room = build(data, layout, { photos: true, camera: cam.C });
    const snap = (scene) => {
      renderer.render(scene, camera);
      const c = document.createElement("canvas"); c.width = w; c.height = h;
      c.getContext("2d").drawImage(renderer.domElement, 0, 0);
      return c;
    };
    // 1-o'tish: pardoz (pol, devor, ship) — soyasiz
    const sceneA = new THREE.Scene();
    lights(sceneA, layout, false, renderer);
    sceneA.add(room.finishes);
    const finishes = snap(sceneA);
    // 2-o'tish: mebellar + polga tushgan soya
    const sceneB = new THREE.Scene();
    lights(sceneB, layout, true, renderer);
    const catcher = new THREE.Mesh(new THREE.PlaneGeometry(layout.W, layout.D), new THREE.ShadowMaterial({ opacity: 0.38 }));
    catcher.rotation.x = -Math.PI / 2; catcher.position.y = 0.001; catcher.receiveShadow = true;
    sceneB.add(catcher, room.furniture);
    const furniture = snap(sceneB);

    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(photo, 0, 0, w, h);
    // Rasmdagi yorug'lik/soya yangi pardozga o'tadi (faktura emas — kuchli xiralashtirilgan yorqinlik)
    const shade = document.createElement("canvas"); shade.width = w; shade.height = h;
    const sc = shade.getContext("2d");
    sc.drawImage(finishes, 0, 0);
    if (typeof sc.filter === "string") {  // Safari'da filter yo'q — fakturasi o'tib ketmasin, soyasiz qoladi
      sc.globalCompositeOperation = "multiply";
      sc.globalAlpha = 0.55;
      sc.filter = `grayscale(1) blur(${Math.round(w / 40)}px) brightness(1.7)`;
      sc.drawImage(photo, 0, 0, w, h);
      sc.filter = "none"; sc.globalAlpha = 1;
      sc.globalCompositeOperation = "destination-in";
      sc.drawImage(finishes, 0, 0);
    }
    ctx.drawImage(shade, 0, 0);
    // Derazalar (va eshik yangilanmasa — eshik) rasmdagi asli bilan qoladi
    for (const o of layout.openings) {
      if (!o.box || (o.kind === "door" && data.eshik)) continue;
      const [x1, y1, x2, y2] = o.box;
      ctx.save(); ctx.beginPath(); ctx.rect(x1 * w, y1 * h, (x2 - x1) * w, (y2 - y1) * h); ctx.clip();
      ctx.drawImage(photo, 0, 0, w, h); ctx.restore();
    }
    ctx.drawImage(matchPhoto(furniture, photo, w, h), 0, 0);
    addGrain(ctx, w, h);

    return room.tags.map((t) => {
      const p = project(cam, [t.p.x, t.p.y, t.p.z]);
      return p && p[0] > 0.02 && p[0] < 0.98 && p[1] > 0.03 && p[1] < 0.97 ? { n: t.n, x: p[0] * 100, y: p[1] * 100 } : null;
    }).filter(Boolean);
  }

  // 3D qatlamni rasmga moslash: rasmdagi yorug'lik taqsimoti va rang tusi (oq balans), ozgina yumshatish
  function matchPhoto(layer, photo, w, h) {
    const out = document.createElement("canvas"); out.width = w; out.height = h;
    const c = out.getContext("2d");
    const filters = typeof c.filter === "string";
    if (filters) c.filter = "blur(0.5px)";
    c.drawImage(layer, 0, 0);
    if (!filters) return out;
    c.filter = "none";
    const probe = document.createElement("canvas"); probe.width = probe.height = 8;
    const pc = probe.getContext("2d"); pc.drawImage(photo, 0, 0, 8, 8);
    const px = pc.getImageData(0, 0, 8, 8).data;
    let r = 0, g = 0, b = 0;
    for (let i = 0; i < px.length; i += 4) { r += px[i]; g += px[i + 1]; b += px[i + 2]; }
    const m = Math.max(r, g, b) || 1;
    c.globalCompositeOperation = "multiply";
    c.globalAlpha = 0.22;
    c.fillStyle = `rgb(${Math.round(255 * r / m)},${Math.round(255 * g / m)},${Math.round(255 * b / m)})`;
    c.fillRect(0, 0, w, h);
    c.globalAlpha = 0.3;
    c.filter = `grayscale(1) blur(${Math.round(w / 30)}px) brightness(1.6)`;
    c.drawImage(photo, 0, 0, w, h);
    c.filter = "none"; c.globalAlpha = 1;
    c.globalCompositeOperation = "destination-in";
    c.drawImage(layer, 0, 0);
    return out;
  }
  // Kamera sensori shovqini — kompyuter grafikasining "toza plastik" ko'rinishini yo'qotadi
  function addGrain(ctx, w, h) {
    const n = document.createElement("canvas"); n.width = w; n.height = h;
    const nc = n.getContext("2d"), img = nc.createImageData(w, h), d = img.data;
    for (let i = 0; i < d.length; i += 4) { const v = 128 + (Math.random() - 0.5) * 46; d[i] = d[i + 1] = d[i + 2] = v; d[i + 3] = 255; }
    nc.putImageData(img, 0, 0);
    ctx.save(); ctx.globalCompositeOperation = "overlay"; ctx.globalAlpha = 0.22; ctx.drawImage(n, 0, 0); ctx.restore();
  }

  window.Room3D = { solve, defaultLayout, dollhouse, composite, loadPhotos };
})();
