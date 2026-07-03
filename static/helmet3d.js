/**
 * GazMonitor Pro — Casque 3D EN 397 blanc + prototype IoT
 * Reproduit : coque industrielle blanche, capteur MQ frontal,
 * anneau LED bleu ×8, bandeau latéral R/V/V, ESP32 interne.
 */
(function (global) {
  'use strict';

  const RISK = {
    0: { hex: 0x22c55e, label: 'NORMAL', side: 2 },
    1: { hex: 0xeab308, label: 'MODÉRÉ', side: 1 },
    2: { hex: 0xef4444, label: 'DANGEREUX', side: 0 },
    3: { hex: 0xffffff, label: 'CRITIQUE', side: 0 },
  };
  const HELMET_WHITE = 0xfafaf8;
  const SENSOR_MAX_PPM = 31;
  const FRONT_RING_BLUE = 0x3b82f6;
  const HELMET_PHOTO_SRC = '/static/casque_iot.png';

  function hex(v) {
    if (typeof v === 'number') return v;
    return parseInt(String(v).replace('#', ''), 16);
  }

  class Helmet3D {
    constructor(containerId) {
      this.container = document.getElementById(containerId);
      if (!this.container || !global.THREE) return;

      this.view = 'orbit';
      this.standby = true;
      this.data = null;
      this.fleet = {};
      this.fleetMode = false;
      this.t = 0;
      this._pulse = 0;
      this._fireParts = [];
      this._h2sParts = [];

      this._initScene();
      this._buildPhotoReference();
      this._buildHelmet();
      this._buildFleetGhosts();
      this._bindEvents();
      this._animate();
      this.setStandby(true);
    }

    _initScene() {
      const THREE = global.THREE;
      const w = this.container.clientWidth || 400;
      const h = Math.max(this.container.clientHeight || 280, 200);

      this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      this.renderer.setSize(w, h);
      this.renderer.setClearColor(0x000000, 0);
      this.renderer.outputColorSpace = THREE.SRGBColorSpace;
      this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
      this.renderer.toneMappingExposure = 1.12;
      this.renderer.shadowMap.enabled = true;
      this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      this.container.appendChild(this.renderer.domElement);

      this.scene = new THREE.Scene();
      this.scene.fog = new THREE.FogExp2(0x0b1220, 0.035);
      this.camera = new THREE.PerspectiveCamera(36, w / h, 0.1, 100);
      this.camera.position.set(-0.62, 0.08, 2.65);

      this.scene.add(new THREE.HemisphereLight(0xf8fafc, 0x243044, 0.82));
      this.scene.add(new THREE.AmbientLight(0xffffff, 0.18));
      const key = new THREE.DirectionalLight(0xffffff, 1.65);
      key.position.set(-4.5, 6.5, 5.5);
      key.castShadow = true;
      key.shadow.mapSize.set(1024, 1024);
      key.shadow.camera.near = 0.5;
      key.shadow.camera.far = 14;
      key.shadow.camera.left = -3.2;
      key.shadow.camera.right = 3.2;
      key.shadow.camera.top = 3.2;
      key.shadow.camera.bottom = -3.2;
      this.scene.add(key);
      const fill = new THREE.DirectionalLight(0xbad7ff, 0.74);
      fill.position.set(5.5, 2.8, -3.8);
      this.scene.add(fill);
      const rim = new THREE.DirectionalLight(0xdbeafe, 0.68);
      rim.position.set(0.8, 0.8, -5.2);
      this.scene.add(rim);
      this.sceneGlow = new THREE.PointLight(0x38bdf8, 0.45, 5.5);
      this.sceneGlow.position.set(-1.9, 0.55, 1.6);
      this.scene.add(this.sceneGlow);

      this.root = new THREE.Group();
      this.scene.add(this.root);

      this.haloLight = new THREE.PointLight(0x22c55e, 0, 5);
      this.haloLight.position.set(0, 0.15, 0.5);
      this.root.add(this.haloLight);

      this.grid = new THREE.GridHelper(4.4, 14, 0x334155, 0x1e293b);
      this.grid.position.y = -1.05;
      this.grid.material.opacity = 0.18;
      this.grid.material.transparent = true;
      this.scene.add(this.grid);

      this.platformBase = new THREE.Mesh(
        new THREE.CircleGeometry(1.62, 96),
        new THREE.MeshBasicMaterial({ color: 0x111827, transparent: true, opacity: 0.74, side: THREE.DoubleSide })
      );
      this.platformBase.rotation.x = -Math.PI / 2;
      this.platformBase.position.y = -1.04;
      this.platformBase.position.z = 0.04;
      this.scene.add(this.platformBase);

      this.platformRim = new THREE.Mesh(
        new THREE.RingGeometry(1.62, 1.67, 96),
        new THREE.MeshBasicMaterial({ color: 0x22c55e, transparent: true, opacity: 0.2, side: THREE.DoubleSide })
      );
      this.platformRim.rotation.x = -Math.PI / 2;
      this.platformRim.position.y = -1.035;
      this.platformRim.position.z = 0.04;
      this.scene.add(this.platformRim);

      const shadow = new THREE.Mesh(
        new THREE.CircleGeometry(1.08, 64),
        new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.30 })
      );
      shadow.rotation.x = -Math.PI / 2;
      shadow.position.y = -1.015;
      shadow.position.z = 0.08;
      this.scene.add(shadow);
    }

    _buildPhotoReference() {
      const THREE = global.THREE;
      if (!THREE.TextureLoader) return;
      const loader = new THREE.TextureLoader();
      loader.load(HELMET_PHOTO_SRC, (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        const mat = new THREE.SpriteMaterial({
          map: tex,
          transparent: true,
          opacity: 0.92,
          depthTest: false,
        });
        this.photoReference = new THREE.Sprite(mat);
        this.photoReference.scale.set(0.62, 0.50, 1);
        this.photoReference.position.set(-1.18, 0.43, 0.08);
        this.photoReference.renderOrder = 30;
        this.scene.add(this.photoReference);
      }, undefined, () => {});
    }

    _makeStippleBump() {
      const THREE = global.THREE;
      const s = 256;
      const c = document.createElement('canvas');
      c.width = c.height = s;
      const ctx = c.getContext('2d');
      const img = ctx.createImageData(s, s);
      for (let i = 0; i < img.data.length; i += 4) {
        const n = 200 + Math.floor(Math.random() * 55);
        img.data[i] = img.data[i + 1] = img.data[i + 2] = n;
        img.data[i + 3] = 255;
      }
      ctx.putImageData(img, 0, 0);
      const tex = new THREE.CanvasTexture(c);
      tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
      tex.repeat.set(6, 6);
      return tex;
    }

    _shellMaterial() {
      const THREE = global.THREE;
      const bump = this._makeStippleBump();
      this._bumpTex = bump;
      return new THREE.MeshPhysicalMaterial({
        color: HELMET_WHITE,
        roughness: 0.31,
        metalness: 0.02,
        clearcoat: 0.58,
        clearcoatRoughness: 0.16,
        reflectivity: 0.68,
        bumpMap: bump,
        bumpScale: 0.00038,
      });
    }

    /* Profil lathe EN 397 — coque + visière intégrée */
    _buildShellEN397() {
      const THREE = global.THREE;
      const mat = this.shellMat;
      this.shellParts = [];

      const profile = [
        [0.920, -0.272],
        [0.942, -0.222],
        [0.928, -0.182],
        [0.878, -0.132],
        [0.832, -0.072],
        [0.802, -0.012],
        [0.778, 0.068],
        [0.748, 0.152],
        [0.705, 0.242],
        [0.648, 0.332],
        [0.572, 0.418],
        [0.468, 0.492],
        [0.338, 0.548],
        [0.188, 0.562],
        [0.062, 0.548],
        [0.028, 0.532],
      ];
      const pts = profile.map(([x, y]) => new THREE.Vector2(x, y));
      const lathe = new THREE.LatheGeometry(pts, 80);
      lathe.computeVertexNormals();
      this.shell = new THREE.Mesh(lathe, mat);
      this.shell.scale.set(1.0, 1.0, 1.16);
      this.shell.castShadow = true;
      this.shellGroup.add(this.shell);
      this.shellParts.push(this.shell);

      /* Visière avant prolongée (asymétrie) */
      this.brimPeak = new THREE.Mesh(
        new THREE.BoxGeometry(0.52, 0.028, 0.20, 6, 1, 4),
        mat
      );
      this.brimPeak.position.set(0, -0.222, 0.82);
      this.brimPeak.rotation.x = -0.42;
      this.shellGroup.add(this.brimPeak);
      this.shellParts.push(this.brimPeak);

      const peakLip = new THREE.Mesh(
        new THREE.BoxGeometry(0.50, 0.012, 0.025),
        mat
      );
      peakLip.position.set(0, -0.232, 0.88);
      peakLip.rotation.x = -0.38;
      this.shellGroup.add(peakLip);

      /* Gouttière anti-pluie sur le pourtour de la visière */
      const gutter = new THREE.Mesh(
        new THREE.TorusGeometry(0.895, 0.007, 6, 80, Math.PI * 1.55),
        mat
      );
      gutter.rotation.x = Math.PI / 2;
      gutter.rotation.z = Math.PI * 0.72;
      gutter.position.set(0, -0.148, 0.06);
      this.shellGroup.add(gutter);

      /* Trois nervures longitudinales (crête centrale + latérales) */
      this.ridgeGroup = new THREE.Group();
      const ridgeDefs = [
        { x: 0, r: 0.044, len: 0.70, y: 0.548, z: -0.02 },
        { x: -0.138, r: 0.028, len: 0.56, y: 0.508, z: -0.03 },
        { x: 0.138, r: 0.028, len: 0.56, y: 0.508, z: -0.03 },
      ];
      ridgeDefs.forEach((rd) => {
        const rib = new THREE.Mesh(
          new THREE.CapsuleGeometry(rd.r, rd.len, 5, 12),
          mat
        );
        rib.rotation.x = Math.PI / 2 + 0.06;
        rib.position.set(rd.x, rd.y, rd.z);
        this.ridgeGroup.add(rib);
        this.shellParts.push(rib);
      });
      this.shellGroup.add(this.ridgeGroup);

      /* Plaque frontale logo / support lampe */
      this.frontPad = new THREE.Mesh(
        new THREE.BoxGeometry(0.17, 0.105, 0.032),
        mat
      );
      this.frontPad.position.set(0, 0.06, 0.70);
      this.frontPad.rotation.x = -0.22;
      this.shellGroup.add(this.frontPad);
      this.shellParts.push(this.frontPad);

      /* Embases accessoires côté (oreillettes / écran facial) ×3 */
      this.sideBossGroup = new THREE.Group();
      [-0.18, 0.02, 0.20].forEach((z, i) => {
        const boss = new THREE.Mesh(
          new THREE.BoxGeometry(0.038, 0.095, 0.125),
          mat
        );
        boss.position.set(0.872, -0.025, z);
        this.sideBossGroup.add(boss);
        if (i === 1) {
          const slot = new THREE.Mesh(
            new THREE.BoxGeometry(0.014, 0.055, 0.09),
            new THREE.MeshStandardMaterial({ color: 0x3a3a3a, roughness: 0.85 })
          );
          slot.position.set(0.893, -0.025, z);
          this.sideBossGroup.add(slot);
        }
      });
      [-0.18, 0.20].forEach((z) => {
        const bump = new THREE.Mesh(
          new THREE.BoxGeometry(0.028, 0.045, 0.06),
          mat
        );
        bump.position.set(0.855, 0.02, z + 0.12);
        this.sideBossGroup.add(bump);
      });
      this.shellGroup.add(this.sideBossGroup);
      this.shellParts.push(this.sideBossGroup);

      /* Relevé moulé côté avant */
      const sideLug = new THREE.Mesh(
        new THREE.BoxGeometry(0.05, 0.035, 0.07),
        mat
      );
      sideLug.position.set(0.84, 0.04, 0.38);
      this.shellGroup.add(sideLug);
    }

    _createMiniShell() {
      const THREE = global.THREE;
      const g = new THREE.Group();
      const mat = new THREE.MeshStandardMaterial({
        color: HELMET_WHITE, roughness: 0.32, metalness: 0.04,
      });
      const pts = [
        [0.915, -0.265], [0.935, -0.215], [0.865, -0.125], [0.790, 0.000],
        [0.690, 0.255], [0.420, 0.500], [0.120, 0.555], [0.035, 0.540],
      ].map(([x, y]) => new THREE.Vector2(x, y));
      const body = new THREE.Mesh(new THREE.LatheGeometry(pts, 36), mat);
      body.scale.set(1, 1, 1.14);
      g.add(body);
      const peak = new THREE.Mesh(new THREE.BoxGeometry(0.48, 0.026, 0.19), mat);
      peak.position.set(0, -0.218, 0.80);
      peak.rotation.x = -0.40;
      g.add(peak);
      const rib = new THREE.Mesh(new THREE.CapsuleGeometry(0.038, 0.55, 4, 8), mat);
      rib.rotation.x = Math.PI / 2 + 0.06;
      rib.position.set(0, 0.52, -0.03);
      g.add(rib);
      return g;
    }

    /* ── Coque EN 397 blanche satinée (référence photo) ─── */
    _buildHelmet() {
      const THREE = global.THREE;
      this.helmet = new THREE.Group();
      this.helmet.rotation.y = -0.42;
      this.root.add(this.helmet);

      this.shellMat = this._shellMaterial();
      this.shellGroup = new THREE.Group();
      this.helmet.add(this.shellGroup);

      this._buildShellEN397();

      this._buildFrontSensor();
      this._buildSideStrip();
      this._buildInternalElectronics();
      this._buildAuxSensors();
      this._buildMiningAccessories();
      this._buildSuspension();
      this._buildDoseRing();
      this._buildLabelSprite();
      this._buildParticles();

      this.helmet.traverse((obj) => {
        if (!obj.isMesh) return;
        obj.castShadow = true;
        obj.receiveShadow = true;
      });
    }

    /* Capteur MQ frontal + anneau LED bleu ×8 (prototype) */
    _buildFrontSensor() {
      const THREE = global.THREE;
      this.frontGroup = new THREE.Group();
      this.frontGroup.position.set(0, -0.06, 0.76);
      this.helmet.add(this.frontGroup);

      const plate = new THREE.Mesh(
        new THREE.BoxGeometry(0.18, 0.032, 0.17),
        new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.42, metalness: 0.05 })
      );
      this.frontGroup.add(plate);

      const sensorBody = new THREE.Mesh(
        new THREE.CylinderGeometry(0.055, 0.06, 0.04, 24),
        new THREE.MeshStandardMaterial({ color: 0xaab2bf, metalness: 0.62, roughness: 0.30 })
      );
      sensorBody.rotation.x = Math.PI / 2;
      sensorBody.position.z = 0.04;
      this.mainSensor = sensorBody;
      this.frontGroup.add(sensorBody);

      const grille = new THREE.Mesh(
        new THREE.CylinderGeometry(0.042, 0.042, 0.008, 16, 1, true),
        new THREE.MeshStandardMaterial({ color: 0x8a9199, metalness: 0.7, roughness: 0.3, side: THREE.DoubleSide })
      );
      grille.rotation.x = Math.PI / 2;
      grille.position.z = 0.062;
      this.frontGroup.add(grille);

      this.ringLeds = [];
      const ringGroup = new THREE.Group();
      ringGroup.position.z = 0.02;
      this.ringGroup = ringGroup;
      this.frontGroup.add(ringGroup);

      for (let i = 0; i < 8; i++) {
        const a = (i / 8) * Math.PI * 2;
        const mat = new THREE.MeshStandardMaterial({
          color: FRONT_RING_BLUE,
          emissive: FRONT_RING_BLUE,
          emissiveIntensity: 0.85,
          roughness: 0.2,
        });
        const led = new THREE.Mesh(new THREE.SphereGeometry(0.016, 10, 10), mat);
        led.position.set(Math.sin(a) * 0.1, Math.cos(a) * 0.1, 0);
        ringGroup.add(led);
        this.ringLeds.push(led);
      }
    }

    /* Bandeau latéral feu tricolore R / V / V */
    _buildSideStrip() {
      const THREE = global.THREE;
      this.sideStrip = new THREE.Group();
      this.sideStrip.position.set(0.88, -0.035, 0.06);
      this.sideStrip.rotation.y = -Math.PI / 2;
      this.helmet.add(this.sideStrip);

      const housing = new THREE.Mesh(
        new THREE.BoxGeometry(0.2, 0.05, 0.06),
        new THREE.MeshStandardMaterial({ color: 0x2a2a2a, roughness: 0.6 })
      );
      this.sideStrip.add(housing);

      const colors = [0xef4444, 0xeab308, 0x22c55e];
      this.trafficLeds = [];
      [-0.06, 0, 0.06].forEach((x, i) => {
        const mat = new THREE.MeshStandardMaterial({
          color: colors[i],
          emissive: colors[i],
          emissiveIntensity: i === 2 ? 0.9 : 0.08,
          roughness: 0.25,
        });
        const led = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.022, 0.012, 16), mat);
        led.rotation.x = Math.PI / 2;
        led.position.set(x, 0, 0.035);
        this.sideStrip.add(led);
        this.trafficLeds.push(led);
      });
    }

    /* Électronique interne (visible X-ray / Exploded) */
    _buildInternalElectronics() {
      const THREE = global.THREE;
      this.internalGroup = new THREE.Group();
      this.internalGroup.position.set(0, 0.05, -0.05);
      this.helmet.add(this.internalGroup);

      const esp = new THREE.Mesh(
        new THREE.BoxGeometry(0.14, 0.2, 0.025),
        new THREE.MeshStandardMaterial({ color: 0x1a1a1a, roughness: 0.7 })
      );
      esp.position.set(0, 0.12, 0);
      esp.rotation.x = -0.15;
      this.esp = esp;
      this.internalGroup.add(esp);

      const ant = new THREE.Mesh(
        new THREE.BoxGeometry(0.02, 0.06, 0.08),
        new THREE.MeshStandardMaterial({ color: 0xc0c4cc, metalness: 0.5, roughness: 0.4 })
      );
      ant.position.set(0, 0.24, 0);
      this.internalGroup.add(ant);

      [[0.04, 0.18, 0.02, 0x3b82f6], [0.04, 0.14, 0.02, 0x22c55e]].forEach(([x, y, z, c]) => {
        const dot = new THREE.Mesh(
          new THREE.SphereGeometry(0.008, 8, 8),
          new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: 1.2 })
        );
        dot.position.set(x, y, z);
        this.internalGroup.add(dot);
      });

      const battery = new THREE.Mesh(
        new THREE.BoxGeometry(0.18, 0.05, 0.1),
        new THREE.MeshStandardMaterial({ color: 0xc8ccd4, metalness: 0.65, roughness: 0.25 })
      );
      battery.position.set(0, -0.08, 0.02);
      this.battery = battery;
      this.internalGroup.add(battery);

      const wireMat = new THREE.MeshBasicMaterial({ color: 0xef4444 });
      [[0, 0.05, 0.4], [0.05, 0.05, 0.4], [-0.05, 0.05, 0.4]].forEach((pos, i) => {
        const w = new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.004, 0.35, 6), wireMat.clone());
        w.material.color.setHex(i === 0 ? 0xef4444 : i === 1 ? 0x111111 : 0xeab308);
        w.position.set(pos[0], pos[1], pos[2]);
        w.rotation.x = Math.PI / 2;
        this.internalGroup.add(w);
      });

      const gps = new THREE.Mesh(
        new THREE.CylinderGeometry(0.035, 0.04, 0.05, 12),
        new THREE.MeshStandardMaterial({ color: 0x2a3444, metalness: 0.5, roughness: 0.4 })
      );
      gps.position.set(0, 0.54, -0.04);
      this.gps = gps;
      this.helmet.add(gps);

      this.gpsLed = new THREE.Mesh(
        new THREE.SphereGeometry(0.012, 8, 8),
        new THREE.MeshStandardMaterial({ color: 0x22c55e, emissive: 0x22c55e, emissiveIntensity: 0.8 })
      );
      this.gpsLed.position.set(0, 0.58, -0.04);
      this.helmet.add(this.gpsLed);
    }

    /* Capteur H2S unique */
    _buildAuxSensors() {
      // Le casque utilise un seul capteur H2S : le capteur frontal principal.
      this.sensors = [];
      this.sensorGroup = new global.THREE.Group();
      this.helmet.add(this.sensorGroup);
    }

    _buildMiningAccessories() {
      const THREE = global.THREE;

      this.accessoryGroup = new THREE.Group();
      this.helmet.add(this.accessoryGroup);

      this.lampGroup = new THREE.Group();
      this.lampGroup.position.set(0, 0.115, 0.835);
      this.lampGroup.rotation.x = -0.18;
      this.accessoryGroup.add(this.lampGroup);

      const lampBack = new THREE.Mesh(
        new THREE.BoxGeometry(0.19, 0.08, 0.045),
        new THREE.MeshStandardMaterial({ color: 0x202733, roughness: 0.55, metalness: 0.25 })
      );
      const lens = new THREE.Mesh(
        new THREE.CylinderGeometry(0.047, 0.047, 0.022, 28),
        new THREE.MeshPhysicalMaterial({
          color: 0xdbeafe, emissive: 0x93c5fd, emissiveIntensity: 0.55,
          roughness: 0.05, metalness: 0.05, transmission: 0.15, transparent: true, opacity: 0.92,
        })
      );
      lens.rotation.x = Math.PI / 2;
      lens.position.z = 0.035;
      this.lampLens = lens;
      this.lampGroup.add(lampBack, lens);

      this.lampBeam = new THREE.Mesh(
        new THREE.ConeGeometry(0.34, 0.95, 36, 1, true),
        new THREE.MeshBasicMaterial({ color: 0x93c5fd, transparent: true, opacity: 0.09, depthWrite: false, side: THREE.DoubleSide })
      );
      this.lampBeam.rotation.x = Math.PI / 2;
      this.lampBeam.position.set(0, 0.105, 1.25);
      this.accessoryGroup.add(this.lampBeam);

      this.oledCanvas = document.createElement('canvas');
      this.oledCanvas.width = 256;
      this.oledCanvas.height = 128;
      this.oledCtx = this.oledCanvas.getContext('2d');
      this.oledTex = new THREE.CanvasTexture(this.oledCanvas);
      this.oledTex.colorSpace = THREE.SRGBColorSpace;
      this.oled = new THREE.Mesh(
        new THREE.PlaneGeometry(0.25, 0.13),
        new THREE.MeshBasicMaterial({ map: this.oledTex, side: THREE.DoubleSide })
      );
      this.oled.position.set(0.91, 0.065, 0.31);
      this.oled.rotation.set(-0.08, -Math.PI / 2, 0.02);
      this.accessoryGroup.add(this.oled);

      this.batteryBars = [];
      this.batteryGauge = new THREE.Group();
      this.batteryGauge.position.set(-0.66, 0.07, 0.42);
      this.batteryGauge.rotation.y = Math.PI / 2.8;
      this.accessoryGroup.add(this.batteryGauge);
      const gaugeBack = new THREE.Mesh(
        new THREE.BoxGeometry(0.17, 0.045, 0.018),
        new THREE.MeshStandardMaterial({ color: 0x1f2937, roughness: 0.5 })
      );
      this.batteryGauge.add(gaugeBack);
      for (let i = 0; i < 4; i++) {
        const mat = new THREE.MeshStandardMaterial({ color: 0x22c55e, emissive: 0x22c55e, emissiveIntensity: 0.45 });
        const bar = new THREE.Mesh(new THREE.BoxGeometry(0.026, 0.026, 0.012), mat);
        bar.position.set(-0.055 + i * 0.036, 0, 0.018);
        this.batteryGauge.add(bar);
        this.batteryBars.push(bar);
      }

      this.wifiGroup = new THREE.Group();
      this.wifiGroup.position.set(0.17, 0.39, -0.06);
      this.helmet.add(this.wifiGroup);
      this.wifiArcs = [];
      for (let i = 0; i < 3; i++) {
        const arc = new THREE.Mesh(
          new THREE.TorusGeometry(0.045 + i * 0.035, 0.004, 6, 36, Math.PI),
          new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.25 + i * 0.16 })
        );
        arc.rotation.x = Math.PI / 2;
        arc.rotation.z = Math.PI;
        arc.position.y = i * 0.018;
        this.wifiGroup.add(arc);
        this.wifiArcs.push(arc);
      }

      this.sensorBadges = [];
      const labels = ['H2S'];
      const badgePos = [
        [0, -0.18, 0.93]
      ];
      labels.forEach((txt, i) => {
        const spr = this._makeSensorBadge(txt);
        spr.position.set(badgePos[i][0], badgePos[i][1], badgePos[i][2]);
        spr.visible = false;
        this.helmet.add(spr);
        this.sensorBadges.push(spr);
      });

      this._drawOled({ risk_class: 0, h2s_mesure: 0, wifi_rssi: 0, gps_valid: true });
    }

    _makeSensorBadge(text) {
      const THREE = global.THREE;
      const c = document.createElement('canvas');
      c.width = 96;
      c.height = 48;
      const ctx = c.getContext('2d');
      ctx.fillStyle = 'rgba(8,13,20,0.88)';
      if (ctx.roundRect) ctx.roundRect(4, 4, c.width - 8, c.height - 8, 10);
      else ctx.fillRect(4, 4, c.width - 8, c.height - 8);
      ctx.fill();
      ctx.strokeStyle = 'rgba(56,189,248,0.55)';
      ctx.lineWidth = 2;
      if (ctx.roundRect) ctx.roundRect(4, 4, c.width - 8, c.height - 8, 10);
      else ctx.strokeRect(4, 4, c.width - 8, c.height - 8);
      ctx.stroke();
      ctx.font = 'bold 24px Inter,Segoe UI,sans-serif';
      ctx.fillStyle = '#dbeafe';
      ctx.textAlign = 'center';
      ctx.fillText(text, 48, 31);
      const tex = new THREE.CanvasTexture(c);
      tex.colorSpace = THREE.SRGBColorSpace;
      const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
      spr.scale.set(0.18, 0.09, 1);
      return spr;
    }

    _drawOled(d) {
      if (!this.oledCtx) return;
      const ctx = this.oledCtx;
      const c = this.oledCanvas;
      const lvl = Math.min(d.risk_class ?? 0, 2);
      const risk = RISK[lvl] || RISK[0];
      const col = '#' + risk.hex.toString(16).padStart(6, '0');
      ctx.clearRect(0, 0, c.width, c.height);
      ctx.fillStyle = '#07111f';
      ctx.fillRect(0, 0, c.width, c.height);
      ctx.fillStyle = col;
      ctx.fillRect(0, 0, 9, c.height);
      ctx.font = 'bold 24px Inter,Segoe UI,sans-serif';
      ctx.fillStyle = col;
      ctx.fillText(risk.label, 22, 34);
      ctx.font = 'bold 34px ui-monospace,Consolas,monospace';
      ctx.fillStyle = '#e5f2ff';
      ctx.fillText(`${(d.h2s_mesure || 0).toFixed(1)} ppm`, 22, 78);
      const gps = d.gps_valid === false ? 'GPS --' : `GPS ${d.satellites || 0}`;
      const wifi = d.wifi_rssi ? `${d.wifi_rssi} dBm` : 'WiFi --';
      ctx.font = '17px Inter,Segoe UI,sans-serif';
      ctx.fillStyle = '#93a4b8';
      ctx.fillText(`${gps}  ${wifi}`, 22, 110);
      this.oledTex.needsUpdate = true;
    }

    _buildSuspension() {
      const THREE = global.THREE;
      this.suspensionGroup = new THREE.Group();
      this.suspensionGroup.position.set(-0.12, -0.30, -0.28);
      this.helmet.add(this.suspensionGroup);

      const bandMat = new THREE.MeshStandardMaterial({ color: 0x141414, roughness: 0.9 });
      const band = new THREE.Mesh(new THREE.TorusGeometry(0.40, 0.016, 8, 28, Math.PI * 0.85), bandMat);
      band.rotation.x = 0.35;
      band.rotation.z = 0.25;
      this.suspensionGroup.add(band);

      const pad = new THREE.Mesh(
        new THREE.BoxGeometry(0.14, 0.04, 0.06),
        new THREE.MeshStandardMaterial({ color: 0x1a1a1a, roughness: 0.88 })
      );
      pad.position.set(-0.05, -0.04, 0.08);
      this.suspensionGroup.add(pad);

      const ratchet = new THREE.Mesh(
        new THREE.CylinderGeometry(0.045, 0.045, 0.028, 16),
        new THREE.MeshStandardMaterial({ color: 0xfafaf8, roughness: 0.5 })
      );
      ratchet.position.set(0.12, 0.02, -0.15);
      ratchet.rotation.z = Math.PI / 2;
      this.suspensionGroup.add(ratchet);

      const rivet = new THREE.Mesh(
        new THREE.CylinderGeometry(0.012, 0.012, 0.008, 10),
        new THREE.MeshStandardMaterial({ color: 0xb0b4bc, metalness: 0.7, roughness: 0.3 })
      );
      rivet.position.set(0.08, 0.04, -0.08);
      rivet.rotation.x = Math.PI / 2;
      this.suspensionGroup.add(rivet);
    }

    _buildDoseRing() {
      const THREE = global.THREE;
      this.doseRing = new THREE.Mesh(
        new THREE.TorusGeometry(1.08, 0.015, 8, 64),
        new THREE.MeshBasicMaterial({ color: 0xeab308, transparent: true, opacity: 0, side: THREE.DoubleSide })
      );
      this.doseRing.rotation.x = Math.PI / 2;
      this.doseRing.position.y = 0.05;
      this.helmet.add(this.doseRing);
    }

    _buildLabelSprite() {
      const THREE = global.THREE;
      const canvas = document.createElement('canvas');
      canvas.width = 512;
      canvas.height = 128;
      this._labelCanvas = canvas;
      this._labelCtx = canvas.getContext('2d');
      const tex = new THREE.CanvasTexture(canvas);
      tex.colorSpace = global.THREE.SRGBColorSpace;
      this._labelTex = tex;
      this.labelSprite = new THREE.Sprite(
        new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false })
      );
      this.labelSprite.scale.set(1.7, 0.42, 1);
      this.labelSprite.position.set(0, -0.78, 0);
      this.helmet.add(this.labelSprite);
      this._drawLabel('EN VEILLE', '— ppm', '#5d6a82');
    }

    _drawLabel(title, sub, color) {
      const ctx = this._labelCtx;
      const c = this._labelCanvas;
      ctx.clearRect(0, 0, c.width, c.height);
      ctx.fillStyle = 'rgba(8,13,20,0.82)';
      if (ctx.roundRect) ctx.roundRect(8, 8, c.width - 16, c.height - 16, 14);
      else ctx.fillRect(8, 8, c.width - 16, c.height - 16);
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.12)';
      ctx.lineWidth = 2;
      if (ctx.roundRect) ctx.roundRect(8, 8, c.width - 16, c.height - 16, 14);
      else ctx.strokeRect(8, 8, c.width - 16, c.height - 16);
      ctx.stroke();
      ctx.font = 'bold 34px Inter,Segoe UI,sans-serif';
      ctx.fillStyle = color;
      ctx.textAlign = 'center';
      ctx.fillText(title, c.width / 2, 50);
      ctx.font = '22px Inter,Segoe UI,sans-serif';
      ctx.fillStyle = '#9aa7bd';
      ctx.fillText(sub, c.width / 2, 92);
      this._labelTex.needsUpdate = true;
    }

    _buildParticles() {
      const THREE = global.THREE;
      this.fireGroup = new THREE.Group();
      this.h2sGroup = new THREE.Group();
      this.helmet.add(this.fireGroup, this.h2sGroup);

      for (let i = 0; i < 16; i++) {
        const m = new THREE.Mesh(
          new THREE.SphereGeometry(0.018 + Math.random() * 0.025, 6, 6),
          new THREE.MeshBasicMaterial({ color: i % 2 ? 0xff6b00 : 0xff3d00, transparent: true, opacity: 0 })
        );
        m.userData.phase = Math.random() * Math.PI * 2;
        m.userData.speed = 0.4 + Math.random() * 0.5;
        this._fireParts.push(m);
        this.fireGroup.add(m);
      }
      for (let i = 0; i < 10; i++) {
        const m = new THREE.Mesh(
          new THREE.SphereGeometry(0.012, 6, 6),
          new THREE.MeshBasicMaterial({ color: 0xef4444, transparent: true, opacity: 0 })
        );
        m.userData.phase = Math.random() * Math.PI * 2;
        this._h2sParts.push(m);
        this.h2sGroup.add(m);
      }
    }

    _buildFleetGhosts() {
      const THREE = global.THREE;
      this.fleetGroup = new THREE.Group();
      this.fleetGroup.visible = false;
      this.scene.add(this.fleetGroup);
      this.fleetHelmets = [];

      for (let i = 0; i < 4; i++) {
        const g = new THREE.Group();
        const shell = new THREE.Mesh(
          new THREE.SphereGeometry(0.36, 20, 14, 0, Math.PI * 2, 0, Math.PI * 0.55),
          new THREE.MeshStandardMaterial({ color: HELMET_WHITE, roughness: 0.2, metalness: 0.05 })
        );
        shell.position.y = 0.04;
        const strip = new THREE.Mesh(
          new THREE.BoxGeometry(0.12, 0.03, 0.04),
          new THREE.MeshStandardMaterial({ color: 0x22c55e, emissive: 0x22c55e, emissiveIntensity: 0.8 })
        );
        strip.position.set(0.28, 0, 0.05);
        g.add(shell, strip);

        const label = this._makeFleetLabel('—', '#9aa7bd');
        label.position.set(0, -0.42, 0);
        g.add(label);

        g.userData.strip = strip;
        g.userData.label = label;
        g.userData.labelMat = label.material;
        g.position.x = (i - 1.5) * 1.05;
        g.position.y = -0.08;
        g.scale.setScalar(0.62);
        this.fleetGroup.add(g);
        this.fleetHelmets.push(g);
      }
    }

    _makeFleetLabel(text, color) {
      const THREE = global.THREE;
      const canvas = document.createElement('canvas');
      canvas.width = 256;
      canvas.height = 64;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = 'rgba(12,16,24,0.8)';
      ctx.fillRect(0, 0, 256, 64);
      ctx.font = 'bold 22px Inter,Segoe UI,sans-serif';
      ctx.fillStyle = color;
      ctx.textAlign = 'center';
      ctx.fillText(text, 128, 28);
      const tex = new THREE.CanvasTexture(canvas);
      tex.colorSpace = THREE.SRGBColorSpace;
      const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
      spr.scale.set(0.55, 0.14, 1);
      spr.userData.canvas = canvas;
      spr.userData.ctx = ctx;
      spr.userData.tex = tex;
      return spr;
    }

    _updateFleetLabel(sprite, line1, line2, color) {
      const ctx = sprite.userData.ctx;
      const c = sprite.userData.canvas;
      ctx.clearRect(0, 0, c.width, c.height);
      ctx.fillStyle = 'rgba(12,16,24,0.82)';
      ctx.fillRect(0, 0, c.width, c.height);
      ctx.font = 'bold 20px Inter,Segoe UI,sans-serif';
      ctx.fillStyle = color;
      ctx.textAlign = 'center';
      ctx.fillText(line1, 128, 26);
      ctx.font = '16px Inter,Segoe UI,sans-serif';
      ctx.fillStyle = '#9aa7bd';
      ctx.fillText(line2, 128, 50);
      sprite.userData.tex.needsUpdate = true;
    }

    /* ── API ─────────────────────────────────────────────── */
    setView(mode) {
      this.view = mode;
      this._applyViewOffsets(0);
    }

    setStandby(on) {
      this.standby = on;
      if (on) {
        this._setHelmetOpacity(0.72);
        this._drawLabel('NIVEAU 0', 'Securite normale', '#22c55e');
        this.haloLight.color.setHex(0x22c55e);
        this.haloLight.intensity = 0.18;
        this._setRingLeds(0x22c55e, 0.52, false);
        this._setTrafficLeds(2);
        this._drawOled({ risk_class: 0, h2s_mesure: 0, wifi_rssi: 0, gps_valid: true, satellites: 0 });
        if (this.lampLens) {
          this.lampLens.material.emissive.setHex(0x22c55e);
          this.lampLens.material.emissiveIntensity = 0.7;
        }
        if (this.lampBeam) {
          this.lampBeam.material.color.setHex(0x22c55e);
          this.lampBeam.material.opacity = 0.08;
        }
        if (this.platformRim) {
          this.platformRim.material.color.setHex(0x22c55e);
          this.platformRim.material.opacity = 0.24;
        }
      } else {
        this._setHelmetOpacity(1);
      }
    }

    setFleetMode(on, fleetMap) {
      this.fleetMode = on;
      this.fleetGroup.visible = on;
      this.helmet.visible = !on;
      this.grid.visible = !on;
      if (this.photoReference) this.photoReference.visible = !on;
      if (on) {
        this.root.add(this.labelSprite);
        this.labelSprite.position.set(0, -0.88, 0);
      } else {
        this.helmet.add(this.labelSprite);
        this.labelSprite.position.set(0, -0.78, 0);
      }
      if (on && fleetMap) this.updateFleet(fleetMap);
    }

    updateFleet(fleetMap) {
      const ids = Object.keys(fleetMap || {}).sort().slice(0, 4);
      while (ids.length < 4) ids.push(`SLOT_${ids.length + 1}`);
      const now = Date.now();
      let visibleCount = 0;
      ids.forEach((id, i) => {
        const h = this.fleetHelmets[i];
        if (!h) return;
        const entry = fleetMap[id];
        const on = entry && (now - entry.ts < 45000);
        const d = entry ? entry.d : null;
        const lvl = on ? (d.risk_class || 0) : -1;
        const col = lvl >= 0 ? RISK[lvl].hex : 0x5d6a82;
        const colHex = '#' + col.toString(16).padStart(6, '0');
        const strip = h.userData.strip;
        strip.material.color.setHex(col);
        strip.material.emissive.setHex(col);
        strip.material.emissiveIntensity = on ? (lvl === 2 ? 1.35 : 0.85) : 0.05;
        h.visible = this.fleetMode && (on || !!entry);
        if (on) visibleCount++;
        if (h.userData.label) {
          const name = (d && d.worker_name) ? d.worker_name.split(' ').pop() : id.replace('SIM_', 'T');
          const sub = on
            ? `${(d.h2s_mesure || 0).toFixed(1)} ppm · ${RISK[lvl]?.label || '—'}`
            : (entry ? 'Synchronisation…' : 'Hors ligne');
          this._updateFleetLabel(h.userData.label, name, sub, on ? colHex : '#5d6a82');
        }
      });
      if (this.fleetMode) {
        this.standby = false;
        if (visibleCount > 0) {
          this._drawLabel(
            `Flotte — ${visibleCount}/4 travailleurs`,
            'Scénarios simultanés actifs',
            '#2f6df0'
          );
        }
      }
    }

    update(d) {
      if (!d) return;
      this.data = d;
      this.setStandby(false);

      const lvl = Math.min(d.risk_class ?? 0, 3);
      const risk = RISK[lvl] || RISK[0];
      const col = d.risk_color ? hex(d.risk_color) : risk.hex;

      const ringCol = lvl === 0 ? FRONT_RING_BLUE : col;
      this._setRingLeds(ringCol, lvl === 2 ? 1.3 : lvl === 1 ? 0.9 : 0.75, lvl >= 1);
      this._setTrafficLeds(risk.side);
      this._setMainSensor(d);
      this._setAuxSensors(d);
      this._setElectronics(d);
      this._setAccessories(d);
      this._setDose(d);
      this._setFire(d);
      this._setH2sParticles(lvl, d.h2s_mesure || 0);
      this._setShellTint(lvl, col);

      const h2s = (d.h2s_mesure || 0).toFixed(1);
      const pred = d.prediction_ready
        ? `Prédit ${(d.prediction_h2s || 0).toFixed(1)} ppm`
        : 'LSTM en attente';
      const status = lvl === 0 ? 'SÛR' : risk.label;
      this._drawLabel(
        `${d.worker_name || d.device_id || 'Casque'} · ${status}`,
        `H₂S ${h2s} ppm · ${pred}`,
        '#' + col.toString(16).padStart(6, '0')
      );

      this.haloLight.color.setHex(col);
      this.haloLight.position.set(0, 0, 0.85);
      this.haloLight.intensity = lvl === 2 ? 1.5 : lvl === 1 ? 0.5 : 0.1;
      if (this.platformRim) {
        this.platformRim.material.color.setHex(ringCol);
        this.platformRim.material.opacity = lvl === 2 ? 0.46 : lvl === 1 ? 0.34 : 0.22;
      }
      if (this.sceneGlow) {
        this.sceneGlow.color.setHex(ringCol);
        this.sceneGlow.intensity = lvl === 2 ? 0.95 : lvl === 1 ? 0.62 : 0.38;
      }
    }

    _setRingLeds(col, intensity, pulse) {
      this._ledPulse = pulse;
      this._ledIntensity = intensity;
      this._ledColor = col;
      this.ringLeds.forEach((led) => {
        led.material.color.setHex(col);
        led.material.emissive.setHex(col);
        led.material.emissiveIntensity = intensity;
      });
    }

    _setTrafficLeds(activeIndex) {
      const colors = [0xef4444, 0xeab308, 0x22c55e];
      this.trafficLeds.forEach((led, i) => {
        const on = activeIndex === i;
        led.material.emissiveIntensity = on ? 1.1 : 0.06;
        led.material.opacity = on ? 1 : 0.5;
        led.material.transparent = !on;
      });
    }

    _setMainSensor(d) {
      const ppm = +(d.h2s_mesure || d.sensor1 || 0);
      const t = Math.min(ppm / SENSOR_MAX_PPM, 1);
      const lvl = d.risk_class || 0;
      const col = RISK[lvl]?.hex || 0x22c55e;
      this.mainSensor.material.emissive = this.mainSensor.material.emissive || new global.THREE.Color();
      this.mainSensor.material.emissive.setHex(col);
      this.mainSensor.material.emissiveIntensity = 0.1 + t * 0.35;
      const sc = 1 + t * 0.15;
      this.mainSensor.scale.set(sc, sc, 1);
    }

    _setAuxSensors(d) {
      // Capteur unique : l'intensite est geree par le capteur frontal principal.
    }

    _setElectronics(d) {
      const gpsOk = d.gps_valid !== false && (d.satellites || 0) >= 4;
      const gpsCol = gpsOk ? 0x22c55e : 0x5d6a82;
      this.gpsLed.material.color.setHex(gpsCol);
      this.gpsLed.material.emissive.setHex(gpsCol);
      this.gpsLed.material.emissiveIntensity = gpsOk ? 1 : 0.15;

      const temp = d.temperature || 22;
      this.esp.material.emissive = this.esp.material.emissive || new global.THREE.Color();
      this.esp.material.emissive.setHex(temp >= 50 ? 0xff6b00 : 0x111111);
      this.esp.material.emissiveIntensity = temp >= 50 ? 0.4 : 0;
    }

    _setAccessories(d) {
      const lvl = Math.min(d.risk_class ?? 0, 2);
      const risk = RISK[lvl] || RISK[0];
      const ppm = +(d.h2s_mesure || 0);
      const activeColor = lvl === 0 ? 0x93c5fd : risk.hex;

      if (this.lampLens) {
        this.lampLens.material.emissive.setHex(activeColor);
        this.lampLens.material.emissiveIntensity = lvl === 2 ? 1.25 : lvl === 1 ? 0.85 : 0.55;
      }
      if (this.lampBeam) {
        this.lampBeam.material.color.setHex(activeColor);
        this.lampBeam.material.opacity = lvl === 2 ? 0.18 : lvl === 1 ? 0.12 : 0.075;
      }
      if (this.batteryBars) {
        const strength = d.wifi_rssi ? Math.max(1, Math.min(4, Math.ceil((Number(d.wifi_rssi) + 90) / 10))) : 4;
        this.batteryBars.forEach((bar, i) => {
          const on = i < strength;
          const col = strength <= 1 ? 0xef4444 : strength <= 2 ? 0xeab308 : 0x22c55e;
          bar.material.color.setHex(on ? col : 0x334155);
          bar.material.emissive.setHex(on ? col : 0x000000);
          bar.material.emissiveIntensity = on ? 0.45 : 0;
        });
      }
      if (this.wifiArcs) {
        const wifiOk = !d.wifi_rssi || d.wifi_rssi > -78;
        this.wifiArcs.forEach((arc, i) => {
          arc.material.color.setHex(wifiOk ? 0x38bdf8 : 0xeab308);
          arc.material.opacity = wifiOk ? 0.25 + i * 0.16 : 0.08 + i * 0.08;
        });
      }
      if (this.sensorBadges) {
        const visible = this.view === 'sensors' || this.view === 'exploded' || lvl >= 2;
        this.sensorBadges.forEach((badge) => {
          badge.visible = visible;
          badge.scale.setScalar((lvl >= 2 ? 0.19 : 0.16) + Math.min(ppm / SENSOR_MAX_PPM, 1) * 0.03);
        });
      }
      this._drawOled(d);
    }

    _setDose(d) {
      const dose = d.dose_accumulee || 0;
      const exp = d.exposure_level || 'Faible';
      let ringCol = 0xeab308;
      let op = 0;
      if (dose >= 2000 || exp === 'Critique') { ringCol = 0xef4444; op = 0.8; }
      else if (dose >= 500 || exp === 'Eleve') { ringCol = 0xef4444; op = 0.5; }
      else if (dose >= 50 || exp === 'Modere') { ringCol = 0xeab308; op = 0.32; }
      this.doseRing.material.color.setHex(ringCol);
      this.doseRing.material.opacity = op;
    }

    _setFire(d) {
      const fire = d.fire_alert || (d.temperature || 0) >= 50;
      this.fireGroup.visible = !!fire;
      if (fire) {
        this._drawLabel('ALERTE INCENDIE', `Température ${(d.temperature || 0).toFixed(1)}°C`, '#ea580c');
      }
    }

    _setH2sParticles(lvl, ppm) {
      this.h2sGroup.visible = lvl >= 2 || ppm >= 10;
    }

    _setShellTint(lvl, col) {
      if (lvl >= 2) {
        this.shellMat.emissive.setHex(col);
        this.shellMat.emissiveIntensity = 0.06;
      } else if (lvl === 1) {
        this.shellMat.emissive.setHex(col);
        this.shellMat.emissiveIntensity = 0.025;
      } else {
        this.shellMat.emissive.setHex(0x000000);
        this.shellMat.emissiveIntensity = 0;
      }
    }

    _setHelmetOpacity(a) {
      this.helmet.traverse((c) => {
        if (!c.material) return;
        const mats = Array.isArray(c.material) ? c.material : [c.material];
        mats.forEach((m) => {
          if (m.map === this._labelTex) return;
          m.transparent = a < 1;
          m.opacity = a;
        });
      });
    }

    _applyViewOffsets(t) {
      const THREE = global.THREE;
      const e = this.view === 'exploded' ? 1 : this.view === 'xray' ? 0.55 : 0;
      const showInternal = this.view === 'xray' || this.view === 'exploded';

      if (this.shellGroup) this.shellGroup.position.y = e * 0.18;
      if (this.ridgeGroup) this.ridgeGroup.position.y = e * 0.28;
      if (this.brimPeak) this.brimPeak.position.z = 0.80 + e * 0.12;
      if (this.frontPad) this.frontPad.position.z = 0.70 + e * 0.15;
      if (this.frontGroup) this.frontGroup.position.z = 0.76 + e * 0.22;
      if (this.sideStrip) this.sideStrip.position.x = 0.88 + e * 0.12;
      if (this.sideBossGroup) this.sideBossGroup.position.x = e * 0.08;
      if (this.internalGroup) {
        this.internalGroup.visible = showInternal;
        this.internalGroup.position.y = 0.05 - e * 0.12;
      }
      if (this.suspensionGroup) this.suspensionGroup.visible = showInternal || e === 0;
      if (this.sensorGroup) this.sensorGroup.position.y = e * 0.10;
      if (this.gps) this.gps.position.y = 0.54 + e * 0.18;
      if (this.accessoryGroup) this.accessoryGroup.position.z = e * 0.08;
      if (this.wifiGroup) this.wifiGroup.visible = showInternal || this.view === 'sensors';
      if (this.sensorBadges) this.sensorBadges.forEach((b) => { b.visible = this.view === 'sensors' || this.view === 'exploded' || (this.data?.risk_class || 0) >= 2; });

      if (this.view === 'xray') {
        this.shellMat.transparent = true;
        this.shellMat.opacity = 0.20;
        this.shellMat.depthWrite = false;
      } else if (!this.standby) {
        this.shellMat.transparent = false;
        this.shellMat.opacity = 1;
        this.shellMat.depthWrite = true;
      }

      const V3 = THREE.Vector3;
      if (this.view === 'sensors') {
        this.camera.position.lerp(new V3(0.2, -0.02, 1.85), 0.06);
      } else if (this.view === 'orbit') {
        const r = 2.85;
        const base = -0.42;
        this.helmet.rotation.y = base + Math.sin(t * 0.28) * 0.55;
        this.camera.position.x = -0.55 + Math.sin(t * 0.25) * 0.18;
        this.camera.position.z = r + Math.cos(t * 0.25) * 0.1;
        this.camera.position.y = 0.12 + Math.sin(t * 0.4) * 0.04;
      } else {
        this.helmet.rotation.y = -0.42;
        this.camera.position.lerp(new V3(-0.55, 0.12, 2.75), 0.05);
      }
      this.camera.lookAt(0, 0.04, 0.15);
    }

    _animate() {
      requestAnimationFrame(() => this._animate());
      this.t += 0.016;
      this._pulse += 0.016;

      if (this._ledPulse && this.ringLeds) {
        const blink = this.data?.risk_class === 2
          ? 0.45 + Math.sin(this._pulse * 9) * 0.55
          : 0.65 + Math.sin(this._pulse * 3.5) * 0.35;
        this.ringLeds.forEach((led) => {
          led.material.emissiveIntensity = this._ledIntensity * blink;
        });
        if (this.data?.risk_class === 2) {
          this.haloLight.intensity = 1.0 + Math.sin(this._pulse * 9) * 0.7;
          const ti = Math.sin(this._pulse * 9) > 0 ? 1.1 : 0.06;
          if (this.trafficLeds[0]) this.trafficLeds[0].material.emissiveIntensity = ti;
        }
      }

      if (this.fireGroup?.visible) {
        this._fireParts.forEach((p, i) => {
          const ph = p.userData.phase + this.t * p.userData.speed;
          p.position.set(
            Math.sin(ph + i) * 0.3 + 0.1,
            -0.15 + (Math.sin(ph * 2) + 1) * 0.45,
            0.7 + Math.cos(ph + i * 0.7) * 0.2
          );
          p.material.opacity = 0.35 + Math.sin(ph * 3) * 0.3;
        });
      }

      if (this.h2sGroup?.visible) {
        this._h2sParts.forEach((p, i) => {
          const ph = p.userData.phase + this.t * 0.75;
          p.position.set(
            Math.sin(ph + i * 0.5) * 0.5,
            0.05 + Math.sin(ph * 2 + i) * 0.35,
            0.75 + Math.cos(ph + i) * 0.25
          );
          p.material.opacity = 0.12 + Math.sin(ph * 2) * 0.1;
        });
      }

      if (this.doseRing.material.opacity > 0) this.doseRing.rotation.z += 0.007;

      if (this.platformRim) {
        const lvl = this.data?.risk_class ?? 0;
        const base = this.standby ? 0.22 : lvl === 2 ? 0.42 : lvl === 1 ? 0.30 : 0.20;
        const amp = lvl === 2 ? 0.08 : 0.035;
        this.platformRim.material.opacity = base + Math.sin(this.t * (lvl === 2 ? 6.5 : 2.2)) * amp;
      }

      if (this.fleetMode) {
        this.fleetHelmets.forEach((h, i) => {
          h.rotation.y = Math.sin(this.t * 0.5 + i) * 0.12;
        });
      } else if (this.view === 'orbit') {
        /* rotation gérée dans _applyViewOffsets */
      } else {
        this.helmet.rotation.y = -0.42;
      }

      this._applyViewOffsets(this.t);
      this.renderer.render(this.scene, this.camera);
    }

    _bindEvents() {
      const ro = new ResizeObserver(() => {
        const w = this.container.clientWidth;
        const h = this.container.clientHeight;
        if (w && h) {
          this.camera.aspect = w / h;
          this.camera.updateProjectionMatrix();
          this.renderer.setSize(w, h);
        }
      });
      ro.observe(this.container);

      let drag = false, lx = 0, ly = 0;
      this.renderer.domElement.addEventListener('pointerdown', (e) => {
        drag = true; lx = e.clientX; ly = e.clientY;
      });
      global.addEventListener('pointerup', () => { drag = false; });
      global.addEventListener('pointermove', (e) => {
        if (!drag || this.fleetMode) return;
        this.helmet.rotation.y += (e.clientX - lx) * 0.008;
        this.helmet.rotation.x = Math.max(-0.35, Math.min(0.35, this.helmet.rotation.x + (e.clientY - ly) * 0.008));
        lx = e.clientX; ly = e.clientY;
      });
    }

    dispose() {
      this.renderer.dispose();
    }
  }

  global.Helmet3D = Helmet3D;
})(typeof window !== 'undefined' ? window : globalThis);
