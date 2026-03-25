import { useEffect, useRef, useState, useMemo } from "react";

const BACKDROPS = [
  {
    id: "high-plains",
    label: "",
    sky: "linear-gradient(180deg, #0d0d14 0%, #1a1020 55%, #2a1a10 100%)",
    ground: "#1a1008",
    horizon: "#3a2510",
  },
  {
    id: "dust",
    label: "",
    sky: "linear-gradient(180deg, #0a0c18 0%, #141828 55%, #201410 100%)",
    ground: "#120e06",
    horizon: "#2a1e0c",
  },
  {
    id: "night",
    label: "",
    sky: "linear-gradient(180deg, #06080f 0%, #0c1020 60%, #181008 100%)",
    ground: "#0d0a04",
    horizon: "#1e1608",
  },
];

function useTumbleweeds(count = 4) {
  const [weeds, setWeeds] = useState(() =>
    Array.from({ length: count }, (_, i) => ({
      id: i,
      x: -80 - i * 120,
      y: 58 + Math.random() * 22,
      r: 10 + Math.random() * 12,
      speed: 0.18 + Math.random() * 0.22,
      rot: Math.random() * 360,
      rotSpeed: 2.5 + Math.random() * 2.5,
      opacity: 0.55 + Math.random() * 0.35,
      bobOffset: Math.random() * Math.PI * 2,
    }))
  );

  const rafRef = useRef(null);
  const lastRef = useRef(null);

  useEffect(() => {
    const tick = (now) => {
      const dt = lastRef.current == null ? 16 : Math.min(now - lastRef.current, 50);
      lastRef.current = now;
      setWeeds((prev) =>
        prev.map((w) => {
          let x = w.x + w.speed * dt * 0.1;
          let { rot } = w;
          rot = (rot + w.rotSpeed * (dt / 16)) % 360;
          if (x > 420) {
            x = -80 - Math.random() * 60;
          }
          return { ...w, x, rot };
        })
      );
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  return weeds;
}

function TumbleweedSVG({ x, y, r, rot, opacity, bobOffset, time }) {
  const bob = Math.sin(time * 0.003 + bobOffset) * 1.5;
  const actualY = y + bob;
  const spokes = 10;
  const paths = [];
  for (let i = 0; i < spokes; i++) {
    const a = (i / spokes) * Math.PI * 2;
    const len = r * (0.65 + 0.35 * Math.sin(a * 2.3 + 1.1));
    const x2 = Math.cos(a) * len;
    const y2 = Math.sin(a) * len;
    const cx1 = Math.cos(a + 0.4) * len * 0.5;
    const cy1 = Math.sin(a + 0.4) * len * 0.5;
    paths.push(
      <path
        key={i}
        d={`M0,0 Q${cx1},${cy1} ${x2},${y2}`}
        stroke="rgba(160,120,60,0.75)"
        strokeWidth="0.8"
        fill="none"
      />
    );
  }
  const rings = 3;
  for (let ri = 0; ri < rings; ri++) {
    const rr = r * (0.3 + ri * 0.28);
    paths.push(
      <ellipse
        key={`ring-${ri}`}
        cx={0}
        cy={0}
        rx={rr}
        ry={rr * 0.6}
        stroke="rgba(140,100,45,0.45)"
        strokeWidth="0.7"
        fill="none"
        transform={`rotate(${ri * 40})`}
      />
    );
  }
  return (
    <g
      transform={`translate(${x}, ${actualY}) rotate(${rot})`}
      opacity={opacity}
    >
      {paths}
      <circle cx={0} cy={0} r={r} fill="none" stroke="rgba(120,85,35,0.2)" strokeWidth="0.5" />
    </g>
  );
}

function WindLines({ count = 6 }) {
  const lines = useMemo(
    () =>
      Array.from({ length: count }, (_, i) => ({
        id: i,
        y: 30 + i * 11,
        len: 18 + Math.random() * 28,
        delay: i * 0.4,
        opacity: 0.08 + Math.random() * 0.1,
      })),
    []
  );
  return (
    <>
      {lines.map((l) => (
        <line
          key={l.id}
          x1={0}
          y1={l.y}
          x2={l.len}
          y2={l.y}
          stroke="rgba(200,180,140,0.6)"
          strokeWidth="0.5"
          opacity={l.opacity}
          style={{
            animation: `wind-drift ${1.8 + l.delay}s linear infinite`,
            animationDelay: `${l.delay}s`,
          }}
        />
      ))}
    </>
  );
}

export default function Procession({ stage, progress }) {
  const [backdropIndex, setBackdropIndex] = useState(0);
  const [time, setTime] = useState(0);
  const weeds = useTumbleweeds(5);

  useEffect(() => {
    const id = setInterval(() => setBackdropIndex((i) => (i + 1) % BACKDROPS.length), 12000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    let raf;
    const tick = () => { setTime(Date.now()); raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const bd = BACKDROPS[backdropIndex];
  const pct = Math.min(100, Math.max(0, Number(progress) || 0));

  return (
    <>
      <style>{`
        @keyframes wind-drift {
          0% { transform: translateX(-30px); opacity: 0; }
          20% { opacity: 1; }
          80% { opacity: 1; }
          100% { transform: translateX(420px); opacity: 0; }
        }
      `}</style>
      <div
        className="procession-strip"
        role="progressbar"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={stage}
      >
        <div
          className="procession-backdrop"
          style={{ background: bd.sky }}
        >
          <svg
            viewBox="0 0 400 120"
            preserveAspectRatio="xMidYMax meet"
            style={{ width: "100%", height: "100%", position: "absolute", inset: 0 }}
          >
            {/* Stars */}
            {[...Array(28)].map((_, i) => (
              <circle
                key={i}
                cx={(i * 137.5) % 400}
                cy={(i * 53.1) % 55}
                r={0.6 + (i % 3) * 0.4}
                fill="white"
                opacity={0.15 + (i % 5) * 0.08}
              />
            ))}

            {/* Horizon glow */}
            <rect x={0} y={72} width={400} height={6}
              fill={bd.horizon} opacity={0.4} />

            {/* Ground */}
            <rect x={0} y={78} width={400} height={42}
              fill={bd.ground} />

            {/* Ground texture lines */}
            {[82, 88, 96, 108].map((y, i) => (
              <line key={i} x1={0} y1={y} x2={400} y2={y}
                stroke="rgba(255,200,100,0.04)" strokeWidth="0.5" />
            ))}

            {/* Wind lines */}
            <WindLines count={7} />

            {/* Tumbleweeds */}
            {weeds.map((w) => (
              <TumbleweedSVG key={w.id} {...w} time={time} />
            ))}

            {/* Shadow under each weed */}
            {weeds.map((w) => (
              <ellipse
                key={`shadow-${w.id}`}
                cx={w.x}
                cy={80}
                rx={w.r * 0.7}
                ry={w.r * 0.15}
                fill="rgba(0,0,0,0.25)"
                opacity={w.opacity * 0.6}
              />
            ))}
          </svg>
        </div>
      </div>
    </>
  );
}
