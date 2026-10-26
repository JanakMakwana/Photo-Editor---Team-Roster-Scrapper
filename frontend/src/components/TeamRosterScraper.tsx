import React, { useState } from 'react';
import { Player } from '../types';
import { Globe, Download, SlidersHorizontal, CheckCircle2, AlertCircle, FileArchive, ArrowRight } from 'lucide-react';
import JSZip from 'jszip';

interface TeamRosterScraperProps {
  onLoadRosterInWorkbench: (players: Player[], folderName: string) => void;
  onTuneSingleInWorkbench: (player: Player) => void;
}

export const TeamRosterScraper: React.FC<TeamRosterScraperProps> = ({
  onLoadRosterInWorkbench,
  onTuneSingleInWorkbench
}) => {
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [players, setPlayers] = useState<Player[]>([]);
  const [suggestedFolder, setSuggestedFolder] = useState('Roster');
  const [downloadingZip, setDownloadingZip] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState('');

  const samplePresets = [
    { label: 'Cardiff Devils (UK EIHL)', url: 'https://cardiffdevils.com/team' },
    { label: 'Brooks Bandits (BCHL)', url: 'https://bchl.ca/stats/roster/1/60' },
    { label: 'Eisloewen (DEL2)', url: 'https://www.eisloewen.de/team/' },
    { label: 'Red Bull Munich (DEL)', url: 'https://www.redbullmuenchen.de/de/team' }
  ];

  const handleScrape = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!url.trim()) return;

    setLoading(true);
    setError('');
    setPlayers([]);

    try {
      const res = await fetch('/api/fetch_roster', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url.trim() })
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || data.message || 'Scraping failed.');
      }

      setPlayers(data.players || []);
      setSuggestedFolder(data.suggested_folder || 'Roster');
    } catch (err: any) {
      setError(err.message || 'Failed to extract roster from URL.');
    } finally {
      setLoading(false);
    }
  };

  const handleNumberChange = (index: number, newNumber: string) => {
    const updated = [...players];
    updated[index] = { ...updated[index], assigned_number: newNumber };
    setPlayers(updated);
  };

  const handleDownloadZip = async () => {
    if (players.length === 0) return;
    setDownloadingZip(true);
    setDownloadProgress('Preparing batch download...');

    try {
      const zip = new JSZip();
      let completed = 0;

      for (let i = 0; i < players.length; i++) {
        const p = players[i];
        if (!p.image) continue;

        setDownloadProgress(`Fetching portrait ${i + 1} of ${players.length} (${p.name})...`);
        try {
          const res = await fetch(`/api/proxy_photo?url=${encodeURIComponent(p.image)}&width=800`);
          if (res.ok) {
            const blob = await res.blob();
            const num = p.assigned_number || p.number || `${i + 1}`;
            const cleanName = (p.name || 'Athlete').replace(/[^a-zA-Z0-9_\-\s]/g, '').trim();
            const filename = p.assigned_number ? `${num}.png` : `${cleanName}.png`;
            zip.file(filename, blob);
            completed++;
          }
        } catch (e) {
          console.warn(`Failed to fetch photo for ${p.name}`);
        }
      }

      setDownloadProgress('Generating ZIP archive...');
      const zipBlob = await zip.generateAsync({ type: 'blob' });
      const dlUrl = URL.createObjectURL(zipBlob);
      const a = document.createElement('a');
      a.href = dlUrl;
      a.download = `${suggestedFolder}_180x180.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(dlUrl);

      setDownloadProgress('');
    } catch (err: any) {
      alert(`ZIP Download failed: ${err.message}`);
    } finally {
      setDownloadingZip(false);
    }
  };

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', textAlign: 'left' }}>
      {/* URL Scraping Input Box */}
      <div className="saas-card" style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 800, marginBottom: 6 }}>Team Athletic URL Roster Ingestion</h2>
        <p style={{ fontSize: '0.84rem', color: 'var(--text-muted)', marginBottom: 18 }}>
          Paste any sports team roster URL (HUDL, EliteProspects, HockeyTech, College Athletics) to ingest portraits.
        </p>

        <form onSubmit={handleScrape} style={{ display: 'flex', gap: 10 }}>
          <div className="input-icon-wrapper" style={{ flex: 1 }}>
            <Globe className="input-icon" size={16} />
            <input
              type="url"
              className="saas-input"
              placeholder="https://your-team-domain.com/roster"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
            />
          </div>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={loading}
            style={{ padding: '0 24px' }}
          >
            <span>{loading ? 'Ingesting Roster...' : 'Scrape Roster'}</span>
          </button>
        </form>

        {/* Sample Presets */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 14, flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontWeight: 600 }}>Sample Presets:</span>
          {samplePresets.map((p, i) => (
            <button
              key={i}
              type="button"
              className="btn btn-ghost btn-sm"
              style={{ fontSize: '0.74rem', padding: '3px 8px', border: '1px solid var(--border-subtle)', borderRadius: 4 }}
              onClick={() => {
                setUrl(p.url);
              }}
            >
              {p.label}
            </button>
          ))}
        </div>

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

      {/* Roster Results Table */}
      {players.length > 0 && (
        <div className="saas-card" style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <h3 style={{ fontSize: '1.05rem', fontWeight: 800 }}>{suggestedFolder} Roster ({players.length} Athletes)</h3>
              <p style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>Assign jersey numbers and download standardized headshots</p>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => onLoadRosterInWorkbench(players, suggestedFolder)}
              >
                <SlidersHorizontal size={14} />
                <span>Open in Workbench</span>
              </button>
              <button
                className="btn btn-primary btn-sm"
                onClick={handleDownloadZip}
                disabled={downloadingZip}
              >
                <FileArchive size={14} />
                <span>{downloadingZip ? downloadProgress || 'Downloading...' : 'Download All Photos (ZIP)'}</span>
              </button>
            </div>
          </div>

          <div style={{ maxHeight: 520, overflowY: 'auto' }}>
            <table className="saas-table">
              <thead>
                <tr>
                  <th style={{ width: 60 }}>Headshot</th>
                  <th>Athlete Name</th>
                  <th>Position</th>
                  <th style={{ width: 140 }}>Assigned Jersey #</th>
                  <th style={{ textAlign: 'right', width: 160 }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {players.map((p, idx) => (
                  <tr key={idx}>
                    <td>
                      <div style={{ width: 40, height: 40, borderRadius: 6, overflow: 'hidden', border: '1px solid var(--border-subtle)', background: '#f8fafc' }}>
                        {p.image ? (
                          <img
                            src={`/api/proxy_photo?url=${encodeURIComponent(p.image)}&width=100`}
                            alt={p.name}
                            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                          />
                        ) : (
                          <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: '0.65rem', fontWeight: 700 }}>
                            N/A
                          </div>
                        )}
                      </div>
                    </td>
                    <td>
                      <div style={{ fontWeight: 700, fontSize: '0.88rem', color: 'var(--text)' }}>{p.name}</div>
                      {p.team && <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{p.team}</div>}
                    </td>
                    <td style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                      {p.position || p.pos || 'Athlete'}
                    </td>
                    <td>
                      <input
                        type="text"
                        className="saas-input"
                        placeholder={p.number ? `#${p.number}` : '#'}
                        value={p.assigned_number ?? (p.number || '')}
                        onChange={(e) => handleNumberChange(idx, e.target.value)}
                        style={{ width: 90, padding: '6px 10px', fontSize: '0.82rem', textAlign: 'center', fontFamily: 'var(--font-mono)' }}
                      />
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => onTuneSingleInWorkbench(p)}
                      >
                        <SlidersHorizontal size={13} />
                        <span>Tune</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
