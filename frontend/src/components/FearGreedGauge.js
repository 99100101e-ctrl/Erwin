import React from 'react';

const ZONES = [
  { max: 25,  label: 'Extreme Fear',  color: '#ef4444' },
  { max: 45,  label: 'Fear',          color: '#f97316' },
  { max: 55,  label: 'Neutral',       color: '#facc15' },
  { max: 75,  label: 'Greed',         color: '#86efac' },
  { max: 100, label: 'Extreme Greed', color: '#4ade80' },
];

function getZone(value) {
  return ZONES.find(z => value <= z.max) || ZONES[ZONES.length - 1];
}

export default function FearGreedGauge({ data }) {
  if (!data) return null;
  const value = data.value || 50;
  const zone = getZone(value);

  // SVG half-circle gauge
  const size = 160;
  const radius = 60;
  const circumference = Math.PI * radius;
  const progress = (value / 100) * circumference;

  return (
    <div className="glass-card p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wide mb-3">Fear & Greed Index</div>
      <div className="flex items-center gap-4">
        {/* Gauge */}
        <div className="relative flex-shrink-0" style={{ width: size, height: size / 2 + 16 }}>
          <svg width={size} height={size / 2 + 16} viewBox={`0 0 ${size} ${size / 2 + 16}`}>
            {/* Background zones */}
            {ZONES.map((z, i) => {
              const prev = i === 0 ? 0 : ZONES[i - 1].max;
              const startAngle = -180 + (prev / 100) * 180;
              const endAngle = -180 + (z.max / 100) * 180;
              return (
                <path
                  key={i}
                  d={describeArc(size / 2, size / 2 + 8, radius, startAngle, endAngle)}
                  fill="none"
                  stroke={z.color}
                  strokeWidth="12"
                  opacity="0.25"
                />
              );
            })}
            {/* Active progress */}
            <path
              d={describeArc(size / 2, size / 2 + 8, radius, -180, 0)}
              fill="none"
              stroke={zone.color}
              strokeWidth="12"
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={circumference - progress}
              style={{ transition: 'stroke-dashoffset 1s ease-in-out' }}
            />
            {/* Needle */}
            {(() => {
              const angle = -180 + (value / 100) * 180;
              const rad = ((angle) * Math.PI) / 180;
              const nx = size / 2 + (radius - 4) * Math.cos(rad);
              const ny = size / 2 + 8 + (radius - 4) * Math.sin(rad);
              return (
                <line
                  x1={size / 2} y1={size / 2 + 8}
                  x2={nx} y2={ny}
                  stroke="white"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              );
            })()}
            {/* Center dot */}
            <circle cx={size / 2} cy={size / 2 + 8} r="4" fill={zone.color} />
            {/* Value text */}
            <text
              x={size / 2}
              y={size / 2 + 4}
              textAnchor="middle"
              fill="white"
              fontSize="20"
              fontWeight="bold"
            >
              {value}
            </text>
          </svg>
        </div>

        {/* Labels */}
        <div>
          <div className="text-2xl font-bold" style={{ color: zone.color }}>{zone.label}</div>
          <div className="text-xs text-gray-500 mt-1">Index value: {value}/100</div>
          <div className="grid grid-cols-1 gap-1 mt-3">
            {ZONES.map(z => (
              <div key={z.label} className="flex items-center gap-2 text-xs">
                <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: z.color }} />
                <span className={value <= z.max && (ZONES.indexOf(z) === 0 || value > ZONES[ZONES.indexOf(z) - 1].max)
                  ? 'text-white font-semibold' : 'text-gray-500'}>
                  {z.label}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function describeArc(cx, cy, r, startAngle, endAngle) {
  const start = polarToCartesian(cx, cy, r, startAngle);
  const end = polarToCartesian(cx, cy, r, endAngle);
  return `M ${start.x} ${start.y} A ${r} ${r} 0 0 1 ${end.x} ${end.y}`;
}

function polarToCartesian(cx, cy, r, angleDeg) {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}
