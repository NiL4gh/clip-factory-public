"use client";

import { Sparkles, Check, X, ShieldAlert, Award, Clock, Flame, ChevronRight, Activity } from "lucide-react";

interface WordTimestamp {
  word: string;
  start: number;
  end: number;
}

interface LineStrategyInspectorProps {
  clipTitle: string;
  clipStart: number;
  clipEnd: number;
  viralityScore: number;
  explanation?: string;
  wordTimestamps?: WordTimestamp[];
  excludedSentences?: string[];
  viralHookAngles?: Record<string, string>;
  onSelectHookAngle?: (hookText: string) => void;
  onToggleSentence?: (sentenceText: string) => void;
}

export function LineStrategyInspector({
  clipTitle,
  clipStart,
  clipEnd,
  viralityScore,
  explanation,
  wordTimestamps = [],
  excludedSentences = [],
  viralHookAngles = {
    curiosity: `The Secret Behind ${(clipTitle || "This Clip").slice(0, 25)}...`,
    contrarian: `Why Everyone Is Wrong About ${(clipTitle || "This Clip").slice(0, 22)}`,
    financial: `The $100K Secret To ${(clipTitle || "This Clip").slice(0, 25)}`,
    story: `He Didn't Realize What Happened Next...`,
    actionable: `Do This Immediately For Viral Results`,
  },
  onSelectHookAngle,
  onToggleSentence,
}: LineStrategyInspectorProps) {
  // Group word timestamps into coherent sentences based on punctuation or timing gaps
  const sentences = (() => {
    if (!wordTimestamps || wordTimestamps.length === 0) return [];
    
    // Filter words within clip boundaries
    const clipWords = wordTimestamps.filter(
      (w) => w.start >= clipStart - 0.5 && w.end <= clipEnd + 0.5
    );
    if (clipWords.length === 0) return [];

    const result: { text: string; start: number; end: number; wordsCount: number }[] = [];
    let currentWords: string[] = [];
    let startT = clipWords[0].start;
    let endT = clipWords[0].end;

    for (let i = 0; i < clipWords.length; i++) {
      const w = clipWords[i];
      currentWords.push(w.word);
      endT = w.end;

      const isEndPunctuation = /[.!?]$/.test(w.word);
      const isLongPause = i < clipWords.length - 1 && clipWords[i + 1].start - w.end > 0.6;
      const isLengthCap = currentWords.length >= 14;

      if (isEndPunctuation || isLongPause || isLengthCap || i === clipWords.length - 1) {
        result.push({
          text: currentWords.join(" "),
          start: startT,
          end: endT,
          wordsCount: currentWords.length,
        });
        currentWords = [];
        if (i < clipWords.length - 1) {
          startT = clipWords[i + 1].start;
        }
      }
    }
    return result;
  })();

  const durationSec = Math.max(1, Math.round(clipEnd - clipStart));
  const viralityColor =
    viralityScore >= 9.0
      ? "from-emerald-500 to-teal-400 text-emerald-400"
      : viralityScore >= 8.0
      ? "from-indigo-500 to-purple-400 text-indigo-400"
      : "from-amber-500 to-orange-400 text-amber-400";

  return (
    <div className="flex flex-col gap-4 bg-slate-900/90 border border-slate-800 rounded-2xl p-5 backdrop-blur-xl shadow-xl">
      {/* Header & Virality Score Gauge */}
      <div className="flex items-start justify-between gap-4 pb-4 border-b border-slate-800/80">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2.5 py-0.5 rounded-full text-[10px] font-extrabold uppercase tracking-wider bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              Opus AI Reasoning
            </span>
            <span className="text-xs text-slate-400 font-mono flex items-center gap-1">
              <Clock className="w-3 h-3 text-slate-500" />
              {clipStart.toFixed(1)}s – {clipEnd.toFixed(1)}s ({durationSec}s)
            </span>
          </div>
          <h4 className="text-base font-bold text-white tracking-tight leading-snug">
            {clipTitle}
          </h4>

          {/* Viral Hook Studio Angles Selector */}
          {viralHookAngles && (
            <div className="mt-2 space-y-1.5">
              <span className="text-[10px] uppercase font-bold text-slate-400 flex items-center gap-1">
                <Sparkles className="w-3 h-3 text-indigo-400" /> Viral Hook Studio (5 Angles)
              </span>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(viralHookAngles).map(([angleType, hookText]) => (
                  <button
                    key={angleType}
                    type="button"
                    onClick={() => onSelectHookAngle && onSelectHookAngle(hookText)}
                    className="px-2.5 py-1 rounded-lg bg-slate-950 hover:bg-indigo-950/60 border border-slate-800 hover:border-indigo-500/40 text-[10px] font-extrabold text-slate-300 hover:text-white transition-all cursor-pointer truncate max-w-[200px]"
                    title={hookText}
                  >
                    <span className="text-indigo-400 capitalize mr-1">[{angleType}]:</span>
                    <span>{hookText}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Virality Score Badge */}
        <div className="flex flex-col items-end shrink-0">
          <div className="flex items-center gap-1.5 bg-slate-950/80 px-3 py-1.5 rounded-xl border border-slate-800 shadow-inner">
            <Flame className="w-4 h-4 text-amber-400 animate-pulse" />
            <span className={`font-black text-lg bg-gradient-to-r ${viralityColor} bg-clip-text text-transparent`}>
              {viralityScore.toFixed(1)}
            </span>
            <span className="text-[10px] font-bold text-slate-500 uppercase">/10</span>
          </div>
          <span className="text-[9px] font-bold text-slate-400 uppercase tracking-widest mt-1">
            Virality Score
          </span>
        </div>
      </div>

      {/* LLM Hook & Retention Strategy Explanation */}
      {explanation && (
        <div className="bg-indigo-950/30 border border-indigo-500/20 rounded-xl p-3.5 flex items-start gap-3">
          <Sparkles className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <div className="text-[11px] font-bold uppercase tracking-wider text-indigo-300">
              Audience Retention Strategy
            </div>
            <p className="text-xs text-slate-300 leading-relaxed font-normal">
              {explanation}
            </p>
          </div>
        </div>
      )}

      {/* Sentence-by-Sentence Line Inspector */}
      <div className="space-y-2">
        <div className="flex items-center justify-between px-1">
          <span className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
            <Activity className="w-3.5 h-3.5 text-indigo-400" />
            Sentence-by-Sentence Line Strategy ({sentences.length} lines)
          </span>
          <span className="text-[10px] text-slate-500">
            Click any sentence to include/exclude
          </span>
        </div>

        <div className="flex flex-col gap-2 max-h-[320px] overflow-y-auto custom-scrollbar pr-1">
          {sentences.length === 0 ? (
            <div className="p-4 text-center text-xs text-slate-500 italic bg-slate-950/50 rounded-xl border border-slate-800">
              No word-level timestamps available for this clip segment.
            </div>
          ) : (
            sentences.map((sentence, idx) => {
              const isExcluded = excludedSentences.includes(sentence.text);
              return (
                <div
                  key={idx}
                  onClick={() => onToggleSentence && onToggleSentence(sentence.text)}
                  className={`group relative p-3 rounded-xl border transition-all cursor-pointer flex items-start justify-between gap-3 ${
                    isExcluded
                      ? "bg-rose-950/20 border-rose-500/20 text-slate-500 line-through"
                      : "bg-slate-950/60 border-slate-800 hover:border-indigo-500/40 text-slate-200 hover:bg-slate-900/80 shadow-sm"
                  }`}
                >
                  <div className="flex items-start gap-2.5">
                    <span className="text-[10px] font-mono font-bold text-slate-500 bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800 mt-0.5 shrink-0">
                      {sentence.start.toFixed(1)}s
                    </span>
                    <p className="text-xs font-medium leading-relaxed">
                      {sentence.text}
                    </p>
                  </div>

                  <div className="shrink-0 flex items-center gap-1.5 mt-0.5">
                    {isExcluded ? (
                      <span className="flex items-center gap-1 text-[10px] font-bold text-rose-400 bg-rose-500/10 px-2 py-0.5 rounded-full border border-rose-500/20">
                        <X className="w-3 h-3" /> Excluded
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-[10px] font-bold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20 opacity-80 group-hover:opacity-100">
                        <Check className="w-3 h-3" /> Active
                      </span>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
