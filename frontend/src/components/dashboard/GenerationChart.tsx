import React from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { Zap, Activity } from 'lucide-react';

export interface ChartPoint {
  time: string;
  acPower: number;
  dcPower: number;
  isFault?: boolean;
}

interface GenerationChartProps {
  data: ChartPoint[];
  loading?: boolean;
}

export const GenerationChart: React.FC<GenerationChartProps> = ({ data, loading }) => {
  return (
    <div className="bg-white rounded-xl p-4 border border-slate-200/90 shadow-xs space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-3">
        <div>
          <h3 className="text-sm font-bold text-slate-900 tracking-tight">Generation vs Irradiance</h3>
          <p className="text-[11px] text-slate-500 font-mono">Synchronized Diurnal Telemetry Profile</p>
        </div>

        <div className="flex items-center gap-4 text-xs font-mono font-medium">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-[#0284c7]" />
            <span className="text-slate-700">AC (MW)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-[#d97706]" />
            <span className="text-slate-700">DC (MW)</span>
          </div>
        </div>
      </div>

      {/* Chart Area */}
      <div className="h-64 w-full relative">
        {loading ? (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-50/60 backdrop-blur-xs rounded-lg">
            <div className="flex items-center gap-2 text-xs font-mono text-slate-500">
              <Activity className="w-4 h-4 animate-spin text-sky-600" />
              Loading Telemetry Profile...
            </div>
          </div>
        ) : data.length === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center text-xs text-slate-400 font-mono">
            No telemetry data available for selected time range
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="colorAc" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#0284c7" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#0284c7" stopOpacity={0.0} />
                </linearGradient>
                <linearGradient id="colorDc" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#d97706" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#d97706" stopOpacity={0.0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
              <XAxis dataKey="time" stroke="#94a3b8" fontSize={10} tickLine={false} />
              <YAxis stroke="#94a3b8" fontSize={10} tickLine={false} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#004874',
                  borderColor: '#0284c7',
                  borderRadius: '8px',
                  color: '#ffffff',
                  fontSize: '11px',
                  fontFamily: 'monospace',
                }}
                itemStyle={{ color: '#ffffff' }}
              />
              <Area
                type="monotone"
                dataKey="dcPower"
                stroke="#d97706"
                strokeWidth={2}
                fillOpacity={1}
                fill="url(#colorDc)"
                name="DC Power (MW)"
              />
              <Area
                type="monotone"
                dataKey="acPower"
                stroke="#0284c7"
                strokeWidth={2.5}
                fillOpacity={1}
                fill="url(#colorAc)"
                name="AC Power (MW)"
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Footer Banner */}
      <div className="bg-slate-50 rounded-lg p-2.5 border border-slate-200/80 flex flex-col sm:flex-row sm:items-center justify-between text-xs font-mono text-slate-700 gap-2">
        <div className="flex items-center gap-2">
          <Zap className="w-4 h-4 text-amber-500 flex-shrink-0" />
          <span>
            <strong className="text-slate-900">Peak Irradiance:</strong> 942 W/m²
          </span>
          <span className="text-slate-300">|</span>
          <span>
            <strong className="text-slate-900">Grid Export:</strong> 41.2 MW @ 12:45 IST
          </span>
        </div>
        <div className="text-emerald-700 font-semibold bg-emerald-100/80 px-2 py-0.5 rounded text-[11px] self-start sm:self-auto">
          Eff. 98.2% Nominal Band
        </div>
      </div>
    </div>
  );
};
