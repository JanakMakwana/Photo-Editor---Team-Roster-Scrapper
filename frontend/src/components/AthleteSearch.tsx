import React, { useState } from 'react';
import { Player, PhotoOption } from '../types';
import { Search, SlidersHorizontal, CheckCircle2, User, ArrowRight, Download, Sparkles } from 'lucide-react';

interface AthleteSearchProps {
  onTuneInWorkbench: (playerData: { name: string; url: string }) => void;
}

export const AthleteSearch: React.FC<AthleteSearchProps> = ({ onTuneInWorkbench }) => {
  const [playerName, setPlayerName] = useState('');
  const [teamFilter, setTeamFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<any | null>(null);
  const [selectedStintIdx, setSelectedStintIdx] = useState(0);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!playerName.trim()) return;
    setLoading(true);
    setError('');
    setResult(null);

    try {
      const q = new URLSearchParams({ name: playerName.trim() });
      if (teamFilter.trim()) q.set('team', teamFilter.trim());

      const res = await fetch(`/api/search_player?${q.toString()}`);
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || data.message || 'Search failed.');
      }

      setResult(data);
      setSelectedStintIdx(0);
    } catch (err: any) {
      setError(err.message || 'Athlete not found.');
    } finally {
      setLoading(false);
    }
  };

  const currentOption: PhotoOption | null = result?.photo_options?.[selectedStintIdx] || result?.options?.[selectedStintIdx] || null;

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', textAlign: 'left' }}>
      {/* Search Header Form */}
      <div className="saas-card" style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 800, marginBottom: 6 }}>Single Athlete Career Search</h2>
        <p style={{ fontSize: '0.84rem', color: 'var(--text-muted)', marginBottom: 20 }}>
          Search active and historical athletes across sports databases with automatic career stint matching.
        </p>

        <form onSubmit={handleSearch} style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr auto', gap: 12 }}>
          <div className="saas-form-group" style={{ margin: 0 }}>
            <label className="saas-form-label">Athlete Name</label>
            <div className="input-icon-wrapper">
              <Search className="input-icon" size={16} />
              <input
                type="text"
                className="saas-input"
                placeholder="e.g. Connor McDavid, Jordan Eberle"
                value={playerName}
                onChange={(e) => setPlayerName(e.target.value)}
                required
              />
            </div>
          </div>

          <div className="saas-form-group" style={{ margin: 0 }}>
            <label className="saas-form-label">Target Team (Optional)</label>
            <input
              type="text"
              className="saas-input"
              placeholder="e.g. Edmonton Oilers"
              value={teamFilter}
              onChange={(e) => setTeamFilter(e.target.value)}
            />
          </div>

          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={loading}
              style={{ height: 42, padding: '0 20px' }}
            >
              <span>{loading ? 'Searching...' : 'Find Athlete'}</span>
            </button>
          </div>
        </form>

        {error && (
          <div style={{
            marginTop: 14,
            padding: '10px 14px',
            background: 'var(--danger-subtle)',
            border: '1px solid var(--danger-border)',
            color: 'var(--danger)',
            borderRadius: 'var(--r-md)',
            fontSize: '0.82rem'
          }}>
            {error}
          </div>
        )}
      </div>

      {/* Athlete Match Results */}
      {result && (
        <div className="saas-card">
          <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
            {/* 180x180 Headshot Frame */}
            <div style={{
              width: 140,
              height: 140,
              borderRadius: 8,
              border: '1px solid var(--border-subtle)',
              background: '#f8fafc',
              overflow: 'hidden',
              position: 'relative',
              boxShadow: 'var(--shadow-sm)',
              flexShrink: 0
            }}>
              {currentOption?.image ? (
                <img
                  src={`/api/proxy_photo?url=${encodeURIComponent(currentOption.image)}&width=300`}
                  alt={playerName}
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  onError={(e) => {
                    // Fallback to placeholder avatar
                    (e.target as HTMLElement).style.display = 'none';
                  }}
                />
              ) : (
                <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-disabled)' }}>
                  <User size={48} />
                </div>
              )}
              <div style={{
                position: 'absolute',
                bottom: 6,
                right: 6,
                background: 'rgba(15, 23, 42, 0.75)',
                color: '#fff',
                fontSize: '0.62rem',
                fontFamily: 'var(--font-mono)',
                padding: '2px 6px',
                borderRadius: 4
              }}>
                180×180 SPEC
              </div>
            </div>

            {/* Profile Vitals */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 4 }}>
                <h3 style={{ fontSize: '1.35rem', fontWeight: 800 }}>{result.name}</h3>
                {result.is_target_match ? (
                  <span style={{
                    fontSize: '0.72rem',
                    color: 'var(--success)',
                    background: 'var(--success-subtle)',
                    border: '1px solid var(--success-border)',
                    borderRadius: 'var(--r-pill)',
                    padding: '2px 10px',
                    fontWeight: 700
                  }}>
                    Verified Team Match
                  </span>
                ) : (
                  <span style={{
                    fontSize: '0.72rem',
                    color: 'var(--brand-accent)',
                    background: 'var(--brand-accent-subtle)',
                    border: '1px solid var(--brand-accent-border)',
                    borderRadius: 'var(--r-pill)',
                    padding: '2px 10px',
                    fontWeight: 700
                  }}>
                    Career Profile
                  </span>
                )}
              </div>

              <div style={{ fontSize: '0.92rem', fontWeight: 700, color: 'var(--brand-accent)', marginBottom: 8 }}>
                {currentOption?.team || 'Active Career'} {currentOption?.years && `(${currentOption.years})`}
              </div>

              {/* Vitals Chips */}
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
                {currentOption?.years && (
                  <span style={{ background: '#f1f5f9', border: '1px solid #e2e8f0', borderRadius: 4, padding: '3px 8px', fontSize: '0.74rem', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
                    {currentOption.years}
                  </span>
                )}
                {currentOption?.height && (
                  <span style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 4, padding: '3px 8px', fontSize: '0.74rem', color: 'var(--text-secondary)' }}>
                    Ht: {currentOption.height}
                  </span>
                )}
                {currentOption?.weight && (
                  <span style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 4, padding: '3px 8px', fontSize: '0.74rem', color: 'var(--text-secondary)' }}>
                    Wt: {currentOption.weight}
                  </span>
                )}
                {currentOption?.shoots && (
                  <span style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 4, padding: '3px 8px', fontSize: '0.74rem', color: 'var(--text-secondary)' }}>
                    Shoots: {currentOption.shoots}
                  </span>
                )}
              </div>

              <button
                className="btn btn-primary btn-sm"
                onClick={() => onTuneInWorkbench({
                  name: `${result.name}.png`,
                  url: currentOption?.image || ''
                })}
              >
                <SlidersHorizontal size={14} />
                <span>Tune in Workbench</span>
              </button>
            </div>
          </div>

          {/* Stint Switcher */}
          {result.photo_options && result.photo_options.length > 1 && (
            <div style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--border-subtle)' }}>
              <div style={{ fontSize: '0.76rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 10 }}>
                Available Career Stints & Photos ({result.photo_options.length})
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 8 }}>
                {result.photo_options.map((opt: PhotoOption, idx: number) => {
                  const active = idx === selectedStintIdx;
                  return (
                    <div
                      key={idx}
                      onClick={() => setSelectedStintIdx(idx)}
                      style={{
                        padding: '10px 14px',
                        borderRadius: 6,
                        border: `1px solid ${active ? 'var(--brand-accent)' : 'var(--border-subtle)'}`,
                        background: active ? 'var(--brand-accent-subtle)' : '#ffffff',
                        cursor: 'pointer',
                        transition: 'all 0.15s ease'
                      }}
                    >
                      <div style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text)' }}>
                        {opt.team}
                      </div>
                      <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 2 }}>
                        {opt.years || 'Career'} {opt.jersey ? `&bull; #${opt.jersey}` : ''}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
