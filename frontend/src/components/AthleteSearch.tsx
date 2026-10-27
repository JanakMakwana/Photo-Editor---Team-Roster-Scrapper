import React, { useState } from 'react';
import { PhotoOption } from '../types';
import { Search, SlidersHorizontal, User, Sparkles, Building, Calendar, Hash } from 'lucide-react';

interface AthleteSearchProps {
  onTuneInWorkbench: (playerData: { name: string; url: string }) => void;
}

export const AthleteSearch: React.FC<AthleteSearchProps> = ({ onTuneInWorkbench }) => {
  const [playerName, setPlayerName] = useState('');
  const [teamFilter, setTeamFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');
  const [selectedStintIdx, setSelectedStintIdx] = useState(0);

  const sampleAthletes = ['Connor Bedard', 'Connor McDavid', 'Jack Hughes', 'Auston Matthews'];

  const handleSearch = async (e?: React.FormEvent, overrideName?: string) => {
    if (e) e.preventDefault();
    const queryName = overrideName || playerName;
    if (!queryName.trim()) return;

    setLoading(true);
    setError('');
    setResult(null);

    try {
      const q = new URLSearchParams({ name: queryName.trim() });
      if (teamFilter.trim()) q.set('team', teamFilter.trim());

      const res = await fetch(`/api/search_player?${q.toString()}`);
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || data.message || 'Athlete not found.');
      }

      setResult(data);
      setSelectedStintIdx(0);
    } catch (err: any) {
      setError(err.message || 'Athlete not found.');
    } finally {
      setLoading(false);
    }
  };

  const currentOption: PhotoOption | null =
    result?.photo_options?.[selectedStintIdx] || result?.options?.[selectedStintIdx] || null;

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', textAlign: 'left' }}>
      {/* Search Header */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 800, marginBottom: '6px' }}>
          Single Athlete Career Search
        </h2>
        <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '18px' }}>
          Search active and historical athletes across official leagues and sports databases.
        </p>

        <form onSubmit={(e) => handleSearch(e)}>
          <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr auto', gap: '10px' }}>
            <div className="input-wrapper">
              <Search className="input-icon" size={16} />
              <input
                type="text"
                className="input-text"
                placeholder="Athlete name (e.g. Connor Bedard)"
                value={playerName}
                onChange={(e) => setPlayerName(e.target.value)}
                required
              />
            </div>

            <input
              type="text"
              className="input-text"
              placeholder="Team filter (optional)"
              value={teamFilter}
              onChange={(e) => setTeamFilter(e.target.value)}
            />

            <button
              type="submit"
              className="btn btn-primary"
              disabled={loading}
              style={{ padding: '0 20px', height: '40px' }}
            >
              <span>{loading ? 'Searching...' : 'Search'}</span>
            </button>
          </div>
        </form>

        {/* Quick Sample Queries */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '14px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600 }}>Quick search:</span>
          {sampleAthletes.map((name) => (
            <button
              key={name}
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setPlayerName(name);
                handleSearch(undefined, name);
              }}
              style={{
                fontSize: '0.75rem',
                padding: '3px 10px',
                background: 'var(--bg-subtle)',
                borderRadius: 'var(--radius-pill)'
              }}
            >
              {name}
            </button>
          ))}
        </div>

        {error && (
          <div style={{
            marginTop: '14px',
            padding: '10px 14px',
            background: 'var(--danger-light)',
            border: '1px solid var(--danger-border)',
            color: 'var(--danger)',
            borderRadius: 'var(--radius-md)',
            fontSize: '0.8125rem'
          }}>
            {error}
          </div>
        )}
      </div>

      {/* Result Card */}
      {result && (
        <div className="card">
          <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: '24px', alignItems: 'start' }}>
            {/* Standardized 180x180 Spec Frame */}
            <div style={{
              width: 160,
              height: 160,
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border)',
              background: '#f8fafc',
              overflow: 'hidden',
              position: 'relative',
              boxShadow: 'var(--shadow-sm)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              {currentOption?.image ? (
                <img
                  src={`/api/proxy_photo?url=${encodeURIComponent(currentOption.image)}&width=360`}
                  alt={result.name}
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                />
              ) : (
                <User size={48} color="var(--text-muted)" />
              )}
              <div style={{
                position: 'absolute',
                bottom: 6,
                right: 6,
                background: 'rgba(15, 23, 42, 0.75)',
                color: '#fff',
                fontSize: '0.625rem',
                fontFamily: 'var(--font-mono)',
                padding: '2px 6px',
                borderRadius: '4px'
              }}>
                180×180 HUD
              </div>
            </div>

            {/* Profile Info & Actions */}
            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                <div>
                  <h3 style={{ fontSize: '1.25rem', fontWeight: 800 }}>{result.name}</h3>
                  <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
                    {currentOption?.team || 'Professional Athlete'}
                  </div>
                </div>

                {currentOption?.image && (
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={() => onTuneInWorkbench({ name: result.name, url: currentOption.image! })}
                  >
                    <SlidersHorizontal size={14} />
                    <span>Open in Studio</span>
                  </button>
                )}
              </div>

              {/* Career Stints Selector */}
              {result.photo_options && result.photo_options.length > 0 && (
                <div style={{ marginTop: '16px' }}>
                  <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '8px' }}>
                    Available Career Stints ({result.photo_options.length})
                  </div>
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                    {result.photo_options.map((opt: any, idx: number) => {
                      const active = idx === selectedStintIdx;
                      return (
                        <button
                          key={idx}
                          type="button"
                          onClick={() => setSelectedStintIdx(idx)}
                          style={{
                            border: active ? '1px solid var(--brand)' : '1px solid var(--border)',
                            background: active ? 'var(--brand-light)' : '#ffffff',
                            color: active ? 'var(--brand)' : 'var(--text-secondary)',
                            fontWeight: 600,
                            fontSize: '0.75rem',
                            padding: '6px 12px',
                            borderRadius: 'var(--radius-md)',
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '6px'
                          }}
                        >
                          <span>{opt.team || 'Career Stint'}</span>
                          {opt.years && <span style={{ opacity: 0.7 }}>({opt.years})</span>}
                          {opt.jersey && <span>#{opt.jersey}</span>}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
