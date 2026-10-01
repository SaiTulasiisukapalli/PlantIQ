import React from 'react';
import { CheckCircle2, Sliders, Database } from 'lucide-react';
import { Badge } from '../common/Badge';

export interface ColumnMappingItem {
  rawColumn: string;
  mappedKey: string;
  targetType: string;
  confidence: number;
  sampleData?: string;
  valueSpan?: string;
  notes?: string;
}

interface SignalMapperProps {
  fileName?: string;
  rowCount?: number;
  colCount?: number;
  mappings: ColumnMappingItem[];
  onConfirmAll?: () => void;
}

export const SignalMapper: React.FC<SignalMapperProps> = ({
  fileName = 'No file selected',
  rowCount = 0,
  colCount = 0,
  mappings = [],
  onConfirmAll,
}) => {
  return (
    <div className="bg-white rounded-xl p-5 border border-slate-200/90 shadow-xs space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-4">
        <div>
          <span className="text-[10px] font-mono font-bold text-sky-800 uppercase tracking-wider">
            STEP 2 OF 5 : SIGNAL SCHEMA ALIGNMENT
          </span>
          <h3 className="text-base font-bold text-slate-900 tracking-tight">SCADA Column Registry</h3>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={colCount > 0 ? 'emerald' : 'slate'}>
            <CheckCircle2 className="w-3 h-3 inline mr-1" />
            {colCount > 0 ? `${colCount} Auto-Matched` : '0 Columns'}
          </Badge>
        </div>
      </div>

      {/* Target Plant Summary Banner */}
      <div className="bg-sky-50/80 rounded-xl p-4 border border-sky-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-sky-600 text-white flex items-center justify-center font-bold">
            <Database className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-bold text-slate-900">{fileName}</span>
              <Badge variant={rowCount > 0 ? 'emerald' : 'slate'}>
                {rowCount > 0 ? 'PARSED' : 'IDLE'}
              </Badge>
            </div>
            <p className="text-xs text-slate-600">Target: Surya Solar Farm (50MW Phase 1)</p>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3 text-center border-t sm:border-t-0 sm:border-l border-sky-200/60 pt-2 sm:pt-0 sm:pl-4">
          <div>
            <div className="text-[10px] font-mono text-slate-500 uppercase">ROW COUNT</div>
            <div className="text-xs font-bold text-slate-900 font-mono">{rowCount.toLocaleString()}</div>
          </div>
          <div>
            <div className="text-[10px] font-mono text-slate-500 uppercase">COLUMNS</div>
            <div className="text-xs font-bold text-slate-900 font-mono">{colCount} Detected</div>
          </div>
          <div>
            <div className="text-[10px] font-mono text-slate-500 uppercase">CADENCE</div>
            <div className="text-xs font-bold text-sky-700 font-mono">{rowCount > 0 ? '15-Min' : 'N/A'}</div>
          </div>
        </div>
      </div>

      {/* Mappings Cards */}
      <div className="space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs font-mono text-slate-500">
          <span className="font-bold text-slate-700">DETECTED SIGNALS ({mappings.length})</span>
          {onConfirmAll && mappings.length > 0 && (
            <button
              onClick={onConfirmAll}
              className="px-4 py-2 bg-[#004874] hover:bg-[#003354] text-white text-xs font-semibold rounded-lg shadow-sm transition flex items-center justify-center gap-1.5"
            >
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span>Confirm &amp; Execute Ingestion</span>
            </button>
          )}
        </div>

        {mappings.length === 0 ? (
          <div className="p-8 text-center bg-slate-50 rounded-xl border border-slate-200 text-slate-400 font-mono text-xs space-y-1">
            <strong className="text-slate-600 font-bold block">No Signals Registered</strong>
            <span>Upload a SCADA CSV or Parquet file to trigger automated schema profiling &amp; signal mapping.</span>
          </div>
        ) : (
          mappings.map((item, idx) => (
            <div
              key={idx}
              className="p-3.5 bg-slate-50/80 hover:bg-slate-100/60 rounded-xl border border-slate-200/80 transition space-y-2"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 font-mono text-xs">
                  <span className="text-slate-400 font-semibold uppercase text-[10px]">RAW COLUMN</span>
                  <span className="px-2 py-0.5 bg-slate-200/80 rounded font-bold text-slate-800">
                    {item.rawColumn}
                  </span>
                </div>
                <Badge variant={item.confidence >= 99 ? 'emerald' : 'amber'}>
                  {item.confidence}% High
                </Badge>
              </div>

              <div className="flex items-center gap-2 font-mono text-xs pl-2 border-l-2 border-sky-500">
                <span className="text-sky-600 font-bold">↳</span>
                <select className="bg-white border border-slate-200 rounded px-2.5 py-1 text-xs font-semibold text-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-500">
                  <option>{item.mappedKey} ({item.targetType})</option>
                </select>
                <button className="text-[11px] text-sky-600 hover:underline font-semibold ml-auto flex items-center gap-1">
                  <Sliders className="w-3 h-3" /> Edit
                </button>
              </div>

              {(item.sampleData || item.valueSpan || item.notes) && (
                <div className="text-[11px] font-mono text-slate-500 bg-white p-2 rounded border border-slate-100 flex flex-wrap gap-4">
                  {item.sampleData && (
                    <span>
                      <strong className="text-slate-700">SAMPLE DATA:</strong> {item.sampleData}
                    </span>
                  )}
                  {item.valueSpan && (
                    <span>
                      <strong className="text-slate-700">VALUE SPAN:</strong> {item.valueSpan}
                    </span>
                  )}
                  {item.notes && (
                    <span className="text-sky-700 font-medium">
                      🔀 {item.notes}
                    </span>
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {onConfirmAll && mappings.length > 0 && (
        <button
          onClick={onConfirmAll}
          className="w-full py-2.5 bg-[#004874] hover:bg-[#003354] text-white text-xs font-semibold rounded-lg shadow-sm transition flex items-center justify-center gap-2"
        >
          <CheckCircle2 className="w-4 h-4" />
          <span>Confirm Signal Mappings &amp; Execute Ingestion</span>
        </button>
      )}
    </div>
  );
};
