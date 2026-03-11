import React from 'react';

/**
 * Simple SVG arc gauge for signal score 0-100.
 */
export default function SignalGauge({ score = 0, size = 64 }) {
  const radius = (size - 10) / 2;
  const circumference = Math.PI * radius; // half circle
  const progress = Math.min(100, Math.max(0, score));
  const dashOffset = circumference - (progress / 100) * circumference;

  const color =
    progress >= 80 ? '#4ade80' :
    progress >= 60 ? '#facc15' :
    '#64748b';

  return (
    <div className="relative flex items-center justify-center" style={{ width: size, height: size / 2 + 8 }}>
      <svg width={size} height={size / 2 + 8} viewBox={`0 0 ${size} ${size / 2 + 8}`}>
        {/* Background arc */}
        <path
          d={describeArc(size / 2, size / 2 + 4, radius, -180, 0)}
          fill="none"
          stroke="#374151"
          strokeWidth="6"
          strokeLinecap="round"
        />
        {/* Progress arc */}
        <path
          d={describeArc(size / 2, size / 2 + 4, radius, -180, 0)}
          fill="none"
          stroke={color}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          style={{ transition: 'stroke-dashoffset 0.8s ease-in-out, stroke 0.5s' }}
        />
        {/* Score text */}
        <text
          x={size / 2}
          y={size / 2 + 2}
          textAnchor="middle"
          fill={color}
          fontSize="13"
          fontWeight="bold"
          fontFamily="monospace"
        >
          {progress}
        </text>
      </svg>
    </div>
  );
}

function describeArc(cx, cy, r, startAngle, endAngle) {
  const start = polarToCartesian(cx, cy, r, startAngle);
  const end = polarToCartesian(cx, cy, r, endAngle);
  const largeArcFlag = endAngle - startAngle <= 180 ? '0' : '1';
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArcFlag} 1 ${end.x} ${end.y}`;
}

function polarToCartesian(cx, cy, r, angleDeg) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return {
    x: cx + r * Math.cos(rad),
    y: cy + r * Math.sin(rad),
  };
}
