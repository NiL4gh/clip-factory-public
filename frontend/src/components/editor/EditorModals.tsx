"use client";

import { useState, useRef } from "react";
import { Scissors, Wand2, Crop, X, Upload, Check, AlertCircle, Sparkles } from "lucide-react";

interface EditorModalsProps {
  activeModal: "trim" | "watermark" | "crop" | null;
  clipFilename: string;
  clipUrl: string;
  videoDuration?: number;
  onClose: () => void;
  onApplyTrim: (filename: string, startSec: number, endSec: number) => Promise<void>;
  onApplyWatermark: (
    filename: string,
    file: File,
    position: string,
    opacity: number
  ) => Promise<void>;
  onApplyCrop: (filename: string, cropMode: string) => Promise<void>;
}

export function EditorModals({
  activeModal,
  clipFilename,
  clipUrl,
  videoDuration = 0,
  onClose,
  onApplyTrim,
  onApplyWatermark,
  onApplyCrop,
}: EditorModalsProps) {
  const [trimStart, setTrimStart] = useState<number>(0);
  const [trimEnd, setTrimEnd] = useState<number>(videoDuration || 30);
  const [watermarkFile, setWatermarkFile] = useState<File | null>(null);
  const [watermarkPosition, setWatermarkPosition] = useState<string>("bottom-right");
  const [watermarkOpacity, setWatermarkOpacity] = useState<number>(0.85);
  const [cropRatio, setCropRatio] = useState<string>("9:16");
  const [isLoading, setIsLoading] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  if (!activeModal) return null;

  const handleSubmit = async () => {
    setIsLoading(true);
    try {
      if (activeModal === "trim") {
        await onApplyTrim(clipFilename, trimStart, trimEnd);
      } else if (activeModal === "watermark" && watermarkFile) {
        await onApplyWatermark(clipFilename, watermarkFile, watermarkPosition, watermarkOpacity);
      } else if (activeModal === "crop") {
        await onApplyCrop(clipFilename, cropRatio);
      }
      onClose();
    } catch (err) {
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md animate-fadeIn"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-2xl space-y-6 relative overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Glow ambient background */}
        <div className="absolute top-0 right-0 w-64 h-64 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />

        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-4 relative z-10">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
              {activeModal === "trim" && <Scissors className="w-5 h-5 text-indigo-400" />}
              {activeModal === "watermark" && <Wand2 className="w-5 h-5 text-indigo-400" />}
              {activeModal === "crop" && <Crop className="w-5 h-5 text-indigo-400" />}
            </div>
            <div>
              <h3 className="text-lg font-bold text-white tracking-tight capitalize">
                Post-Render {activeModal} Editor
              </h3>
              <p className="text-xs text-slate-400 font-mono truncate max-w-[260px]">
                {clipFilename}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-white rounded-xl hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="space-y-4 relative z-10">
          {/* TRIM MODAL */}
          {activeModal === "trim" && (
            <div className="space-y-4">
              {clipUrl && (
                <video
                  ref={videoRef}
                  src={clipUrl}
                  controls
                  className="w-full h-48 rounded-xl bg-slate-950 object-contain border border-slate-800"
                />
              )}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block mb-1">
                    Start Seconds
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    value={trimStart}
                    onChange={(e) => setTrimStart(parseFloat(e.target.value) || 0)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl p-2.5 text-sm text-white font-mono outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block mb-1">
                    End Seconds
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    value={trimEnd}
                    onChange={(e) => setTrimEnd(parseFloat(e.target.value) || 0)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl p-2.5 text-sm text-white font-mono outline-none focus:border-indigo-500"
                  />
                </div>
              </div>
              <button
                onClick={() => {
                  if (videoRef.current) {
                    setTrimStart(Math.round(videoRef.current.currentTime * 10) / 10);
                  }
                }}
                className="w-full py-2 bg-slate-800 hover:bg-slate-700 text-xs font-bold text-slate-200 rounded-xl transition-all border border-slate-700 cursor-pointer"
              >
                Set Current Video Timestamp as Start
              </button>
            </div>
          )}

          {/* WATERMARK MODAL */}
          {activeModal === "watermark" && (
            <div className="space-y-4">
              <div>
                <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block mb-1.5">
                  Select PNG Logo / Branding Overlay
                </label>
                <input
                  type="file"
                  accept="image/png"
                  onChange={(e) => setWatermarkFile(e.target.files?.[0] || null)}
                  className="w-full text-xs text-slate-300 file:mr-3 file:py-2 file:px-4 file:rounded-xl file:border-0 file:bg-indigo-500/10 file:text-indigo-400 file:font-bold file:cursor-pointer hover:file:bg-indigo-500/20"
                />
              </div>

              {watermarkFile && (
                <div className="flex items-center gap-3 bg-slate-950 p-3 rounded-xl border border-slate-800">
                  <img
                    src={URL.createObjectURL(watermarkFile)}
                    alt="watermark preview"
                    className="w-12 h-12 object-contain bg-slate-900 rounded-lg p-1"
                  />
                  <div className="text-xs">
                    <div className="font-bold text-white">{watermarkFile.name}</div>
                    <div className="text-slate-400">{(watermarkFile.size / 1024).toFixed(1)} KB</div>
                  </div>
                </div>
              )}

              <div>
                <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block mb-1.5">
                  Watermark Position
                </label>
                <select
                  value={watermarkPosition}
                  onChange={(e) => setWatermarkPosition(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl p-2.5 text-sm text-white font-medium outline-none cursor-pointer"
                >
                  <option value="bottom-right">Bottom Right Corner</option>
                  <option value="bottom-left">Bottom Left Corner</option>
                  <option value="top-right">Top Right Corner</option>
                  <option value="top-left">Top Left Corner</option>
                </select>
              </div>

              <div>
                <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block mb-1.5">
                  Opacity ({Math.round(watermarkOpacity * 100)}%)
                </label>
                <input
                  type="range"
                  min="0.1"
                  max="1.0"
                  step="0.05"
                  value={watermarkOpacity}
                  onChange={(e) => setWatermarkOpacity(parseFloat(e.target.value))}
                  className="w-full accent-indigo-500 cursor-pointer"
                />
              </div>
            </div>
          )}

          {/* CROP MODAL */}
          {activeModal === "crop" && (
            <div className="space-y-4">
              <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block mb-1.5">
                Target Reframe Aspect Ratio
              </label>
              <div className="grid grid-cols-3 gap-3">
                {[
                  { id: "9:16", label: "9:16 Vertical", desc: "TikTok / Shorts" },
                  { id: "1:1", label: "1:1 Square", desc: "Feed Posts" },
                  { id: "4:5", label: "4:5 Portrait", desc: "Instagram Feed" },
                ].map((r) => (
                  <button
                    key={r.id}
                    onClick={() => setCropRatio(r.id)}
                    className={`p-3 rounded-xl border text-left transition-all cursor-pointer ${
                      cropRatio === r.id
                        ? "bg-indigo-600/20 border-indigo-500 text-white shadow-md glow-indigo"
                        : "bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700"
                    }`}
                  >
                    <div className="font-extrabold text-sm text-white">{r.label}</div>
                    <div className="text-[10px] text-slate-400 mt-0.5">{r.desc}</div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer Actions */}
        <div className="flex items-center justify-end gap-3 border-t border-slate-800 pt-4 relative z-10">
          <button
            onClick={onClose}
            disabled={isLoading}
            className="px-4 py-2.5 rounded-xl text-xs font-bold text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 transition-all cursor-pointer"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={isLoading || (activeModal === "watermark" && !watermarkFile)}
            className="px-6 py-2.5 rounded-xl text-xs font-bold text-white studio-gradient-btn disabled:opacity-50 cursor-pointer flex items-center gap-2"
          >
            {isLoading ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Processing FFmpeg...
              </>
            ) : (
              <>
                <Check className="w-4 h-4" />
                Apply {activeModal}
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
