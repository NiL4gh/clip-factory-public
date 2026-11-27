import { useState, useEffect } from "react";
import axios from "axios";
import { Card, CardHeader, CardTitle, CardContent } from "./ui/card";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";

interface StorageInfo {
  models: { filename: string; size_mb: number }[];
  sessions: {
    video_id: string;
    url?: string;
    size_mb: number;
    clips_count: number;
    duration: number;
  }[];
}

interface Props {
  API_BASE: string;
  addLog: (msg: string) => void;
}

export function StorageManager({ API_BASE, addLog }: Props) {
  const [storageInfo, setStorageInfo] = useState<StorageInfo>({ models: [], sessions: [] });
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchStorage = async () => {
    try {
      const res = await axios.get(`${API_BASE}/storage`);
      setStorageInfo(res.data);
    } catch (e) {
      // silent fail – UI will show empty state
    }
  };

  useEffect(() => {
    fetchStorage();
  }, [API_BASE]);

  const deleteModel = async (filename: string) => {
    if (!window.confirm(`Are you sure you want to delete the model "${filename}"? This action cannot be undone.`)) return;
    
    setDeletingId(filename);
    try {
      await axios.delete(`${API_BASE}/models/${encodeURIComponent(filename)}`);
      setStorageInfo(prev => ({
        ...prev,
        models: prev.models.filter(m => m.filename !== filename),
      }));
    } catch (e) {
      addLog(`❌ Failed to delete model ${filename}`);
    } finally {
      setDeletingId(null);
    }
  };

  const deleteSession = async (video_id: string) => {
    if (!window.confirm(`Are you sure you want to delete session "${video_id}"? This will delete all generated clips and working files.`)) return;
    
    setDeletingId(video_id);
    try {
      await axios.delete(`${API_BASE}/sessions/${encodeURIComponent(video_id)}`);
      setStorageInfo(prev => ({
        ...prev,
        sessions: prev.sessions.filter(s => s.video_id !== video_id),
      }));
    } catch (e) {
      addLog(`❌ Failed to delete session ${video_id}`);
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Models Section */}
      <div>
        <h4 className="text-sm font-bold text-slate-800 border-b pb-2 mb-3">Local GGUF Models</h4>
        {storageInfo.models.length === 0 && (
          <p className="text-sm text-slate-500 italic">No local models found.</p>
        )}
        <div className="space-y-2">
          {storageInfo.models.map(m => (
            <div key={m.filename} className="flex items-center justify-between bg-slate-50 border border-slate-100 p-2.5 rounded-lg">
              <div>
                <div className="text-sm font-semibold text-slate-700">{m.filename}</div>
                <div className="text-xs text-slate-500">{m.size_mb} MB</div>
              </div>
              <Button
                onClick={() => deleteModel(m.filename)}
                disabled={deletingId === m.filename}
                className="text-rose-500 hover:bg-rose-50 p-1.5 rounded text-xs font-bold disabled:opacity-50"
              >
                {deletingId === m.filename ? 'Deleting...' : 'Delete'}
              </Button>
            </div>
          ))}
        </div>
      </div>

      {/* Sessions Section */}
      <div>
        <h4 className="text-sm font-bold text-slate-800 border-b pb-2 mb-3">Saved Sessions</h4>
        {storageInfo.sessions.length === 0 && (
          <p className="text-sm text-slate-500 italic">No saved sessions found.</p>
        )}
        <div className="space-y-3">
          {storageInfo.sessions.map(s => (
            <div key={s.video_id} className="flex flex-col bg-slate-50 border border-slate-100 p-3 rounded-xl gap-2 shadow-sm">
              <div className="flex justify-between items-start">
                <div className="max-w-[80%] space-y-1">
                  <div className="text-sm font-semibold text-slate-700 truncate" title={s.url || s.video_id}>
                    {s.url ? s.url : `Session: ${s.video_id}`}
                  </div>
                  <div className="flex gap-3 text-[11px] text-slate-500 font-medium">
                    <span>📁 {s.size_mb} MB</span>
                    <span>🎬 {s.clips_count} Clips</span>
                    <span>⏱️ {s.duration ? `${Math.round(s.duration)}s` : 'Unknown'}</span>
                  </div>
                </div>
                <Button
                  onClick={() => deleteSession(s.video_id)}
                  disabled={deletingId === s.video_id}
                  className="text-rose-500 hover:bg-rose-50 p-1.5 rounded-lg text-xs font-bold transition-all disabled:opacity-50"
                >
                  {deletingId === s.video_id ? 'Deleting...' : 'Delete'}
                </Button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
