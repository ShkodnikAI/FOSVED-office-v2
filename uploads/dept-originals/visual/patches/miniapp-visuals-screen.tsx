// ============================================================================
// miniapp-visuals-screen.tsx — Visual Artifacts gallery screen
// ============================================================================
//
// Place at: src/components/screens/visuals-screen.tsx (in fosved-miniapp)
//
// Features:
//   - Grid view of all VisualArtifacts
//   - Filter by tier (1-5) and type
//   - Click to open individual artifact (modal or detail screen)
//   - SVG inline rendering for preview
//   - Recall test button on each card
//
// Register in fosved-app.tsx navigation as new screen "visuals".
// ============================================================================

'use client';

import { useState, useEffect } from 'react';

interface VisualArtifact {
  id: number;
  type: string;
  tier: number;
  templateVersion: string;
  sourceType: string;
  sourceId: number;
  title: string;
  format: string;
  thumbnailUrl: string | null;
  recallTested: boolean;
  recallSuccess: boolean | null;
  publishedToChannel: boolean;
  createdAt: string;
}

const TIER_LABELS: Record<number, string> = {
  1: 'Compression',
  2: 'Memorable',
  3: 'Card',
  4: 'Reference',
  5: 'Premium'
};

const TIER_COLORS: Record<number, string> = {
  1: 'bg-blue-900',
  2: 'bg-amber-700',
  3: 'bg-slate-700',
  4: 'bg-green-800',
  5: 'bg-purple-800'
};

export default function VisualsScreen() {
  const [artifacts, setArtifacts] = useState<VisualArtifact[]>([]);
  const [loading, setLoading] = useState(true);
  const [tierFilter, setTierFilter] = useState<number | null>(null);
  const [selectedArtifact, setSelectedArtifact] = useState<VisualArtifact | null>(null);
  const [artifactContent, setArtifactContent] = useState<string | null>(null);

  useEffect(() => {
    loadArtifacts();
  }, [tierFilter]);

  async function loadArtifacts() {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (tierFilter) params.set('tier', tierFilter.toString());
      params.set('limit', '50');
      const r = await fetch(`/api/visuals?${params}`);
      const data = await r.json();
      setArtifacts(data.artifacts || []);
    } catch (e) {
      console.error('Failed to load visuals:', e);
    } finally {
      setLoading(false);
    }
  }

  async function openArtifact(artifact: VisualArtifact) {
    setSelectedArtifact(artifact);
    setArtifactContent(null);
    try {
      const r = await fetch(`/api/visuals/${artifact.id}`);
      const data = await r.json();
      setArtifactContent(data.content || null);
    } catch (e) {
      console.error('Failed to load artifact content:', e);
    }
  }

  async function recordRecallSuccess(success: boolean) {
    if (!selectedArtifact) return;
    try {
      await fetch('/api/visuals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: selectedArtifact.id,
          recallSuccess: success,
          note: null
        })
      });
      // Refresh
      setSelectedArtifact(null);
      loadArtifacts();
    } catch (e) {
      console.error('Failed to record recall:', e);
    }
  }

  return (
    <div className="p-4 max-w-7xl mx-auto">
      <h1 className="text-2xl font-bold mb-4" style={{ color: '#1a1a2e' }}>
        Visual Archive
      </h1>

      {/* Tier filter */}
      <div className="flex gap-2 mb-4 flex-wrap">
        <button
          onClick={() => setTierFilter(null)}
          className={`px-3 py-1 rounded text-sm ${tierFilter === null ? 'bg-slate-800 text-white' : 'bg-slate-200'}`}
        >
          All ({artifacts.length})
        </button>
        {[1, 2, 3, 4, 5].map(tier => (
          <button
            key={tier}
            onClick={() => setTierFilter(tier === tierFilter ? null : tier)}
            className={`px-3 py-1 rounded text-sm ${tierFilter === tier ? 'bg-slate-800 text-white' : 'bg-slate-200'}`}
          >
            T{tier}: {TIER_LABELS[tier]}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="text-center py-8 text-slate-500">Loading...</div>
      ) : artifacts.length === 0 ? (
        <div className="text-center py-8 text-slate-500">No visuals yet.</div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {artifacts.map(artifact => (
            <div
              key={artifact.id}
              onClick={() => openArtifact(artifact)}
              className="border border-slate-200 rounded-lg overflow-hidden cursor-pointer hover:shadow-lg transition"
              style={{ backgroundColor: '#f5f1e8' }}
            >
              <div className={`px-2 py-1 text-xs text-white ${TIER_COLORS[artifact.tier]}`}>
                T{artifact.tier} · {artifact.type}
              </div>
              <div className="p-3">
                <div className="font-semibold text-sm mb-1 line-clamp-2" style={{ color: '#1a1a2e' }}>
                  {artifact.title}
                </div>
                <div className="text-xs text-slate-500">
                  {artifact.sourceType}/#{artifact.sourceId}
                </div>
                <div className="text-xs text-slate-400 mt-1">
                  {new Date(artifact.createdAt).toISOString().slice(0, 10)}
                </div>
                <div className="flex gap-1 mt-2 text-xs">
                  {artifact.publishedToChannel && (
                    <span className="px-1 bg-blue-100 text-blue-700 rounded">channel</span>
                  )}
                  {artifact.recallTested && (
                    <span className={`px-1 rounded ${artifact.recallSuccess ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                      recall: {artifact.recallSuccess ? '✓' : '✗'}
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Modal for selected artifact */}
      {selectedArtifact && (
        <div
          className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
          onClick={() => setSelectedArtifact(null)}
        >
          <div
            className="bg-white rounded-lg max-w-4xl max-h-[90vh] overflow-auto p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-xl font-bold mb-2">{selectedArtifact.title}</h2>
            <div className="text-sm text-slate-500 mb-4">
              T{selectedArtifact.tier} · {selectedArtifact.type} · template {selectedArtifact.templateVersion} ·{' '}
              source {selectedArtifact.sourceType}/#{selectedArtifact.sourceId}
            </div>

            {artifactContent && selectedArtifact.format === 'svg' ? (
              <div
                className="border border-slate-200 rounded mb-4"
                dangerouslySetInnerHTML={{ __html: artifactContent }}
              />
            ) : artifactContent && selectedArtifact.format === 'spec_json' ? (
              <pre className="text-xs bg-slate-100 p-4 rounded overflow-auto mb-4 max-h-96">
                {artifactContent}
              </pre>
            ) : (
              <div className="py-8 text-center text-slate-500">Loading content...</div>
            )}

            {!selectedArtifact.recallTested && (
              <div className="border-t pt-4 mt-4">
                <div className="text-sm mb-2">
                  <strong>Recall test:</strong> without re-reading the source, what does this infographic say?
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => recordRecallSuccess(true)}
                    className="px-4 py-2 bg-green-700 text-white rounded text-sm"
                  >
                    Successfully recalled
                  </button>
                  <button
                    onClick={() => recordRecallSuccess(false)}
                    className="px-4 py-2 bg-red-700 text-white rounded text-sm"
                  >
                    Could not recall
                  </button>
                </div>
              </div>
            )}

            <button
              onClick={() => setSelectedArtifact(null)}
              className="mt-4 px-4 py-2 bg-slate-200 rounded text-sm"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
