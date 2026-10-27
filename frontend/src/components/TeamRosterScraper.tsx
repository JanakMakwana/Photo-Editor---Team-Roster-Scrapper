import React, { useState } from 'react';
import { Player } from '../types';
import { Globe, Download, SlidersHorizontal, Image as ImageIcon, ExternalLink, Check } from 'lucide-react';
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
  const [players, setPlayers] = useState<Player[]>([]);
  const [suggestedFolder, setSuggestedFolder] = useState('Team_Roster');
  const [error, setError] = useState('');
  const [downloadingZip, setDownloadingZip] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState('');

  const samplePresets = [
    { name: 'Cardiff Devils (EIHL)', url: 'https://www.cardiffdevils.com/team/roster/' },
    { name: 'Nottingham Panthers', url: 'https://www.panthers.co.uk/team/roster' },
    { name: 'Coventry Blaze', url: 'https://coventryblaze.co.uk/team/roster/' },
    { name: 'Penticton Vees (BCHL)', url: 'https://bchl.ca/stats/roster/1/penticton-vees' },
    { name: 'Dresdner Eislöwen (DEL2)', url: 'https://www.eisloewen.de/team/' }
  ];

  const handleScrape = async (e?: React.FormEvent, overrideUrl?: string) => {
    if (e) e.preventDefault();
    const targetUrl = overrideUrl || url;
    if (!targetUrl.trim()) return;

    setLoading(true);
    setError('');

    try {
      const res = await fetch('/api/fetch_roster', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: targetUrl.trim() })
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || data.message || 'Failed to extract roster from URL.');
      }

      setPlayers(data.players || []);
      setSuggestedFolder(data.suggested_folder || 'Team_Roster');
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

      for (let i = 0; i < players.length; i++) {
        const p = players[i];
        if (!p.image) continue;

        setDownloadProgress(`Fetching photo ${i + 1} of ${players.length}...`);
        try {
          const res = await fetch(`/api/proxy_photo?url=${encodeURIComponent(p.image)}&width=800`);
          if (res.ok) {
            const blob = await res.blob();
            const num = p.assigned_number || p.number || `${i + 1}`;
            const cleanName = (p.name || 'Athlete').replace(/[^a-zA-Z0-9_\-\s]/g, '').trim();
            const filename = p.assigned_number ? `${num}.png` : `${cleanName}.png`;
            zip.file(filename, blob);
          }
        } catch (e) {
          console.warn(`Failed to fetch photo for ${p.name}`);
        }
      }

      setDownloadProgress('Packaging ZIP archive...');
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
      alert(`Download failed: ${err.message}`);
    } finally {
      setDownloadingZip(false);
    }
  };

  return (
    <div style={{ maxWidth: 980, margin: '0 auto', textAlign: 'left' }}>
      {/* Header & Scraper Card */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 800, marginBottom: '6px' }}>
          Team Athletic Roster Scraper
        </h2>
        <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '18px' }}>
          Ingest complete sports team rosters directly from URLs (HUDL, EliteProspects, HockeyTech, College).
        </p>

        <form onSubmit={(e) => handleScrape(e)}>
          <div style={{ display: 'flex', gap: '10px' }}>
            <div className="input-wrapper" style={{ flex: 1 }}>
              <Globe className="input-icon" size={16} />
              <input
                type="url"
                className="input-text"
                placeholder="https://team-domain.com/roster"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                required
              />
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={loading}
              style={{ padding: '0 24px', height: '40px' }}
            >
              <span>{loading ? 'Ingesting...' : 'Scrape Roster'}</span>
            </button>
          </div>
        </form>

        {/* Preset Leagues Selector */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '14px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600 }}>Sample Presets:</span>
          {samplePresets.map((preset) => (
            <button
              key={preset.name}
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setUrl(preset.url);
                handleScrape(undefined, preset.url);
              }}
              style={{
                fontSize: '0.75rem',
                padding: '3px 10px',
                background: 'var(--bg-subtle)',
                borderRadius: 'var(--radius-pill)'
              }}
            >
              {preset.name}
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

      {/* Roster Results Table */}
      {players.length > 0 && (
        <div className="card" style={{ padding: '20px' }}>
          {/* Table Action Header */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '16px',
            flexWrap: 'wrap',
            gap: '12px'
          }}>
            <div>
              <h3 style={{ fontSize: '1.125rem', fontWeight: 800 }}>{suggestedFolder}</h3>
              <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
                {players.length} Athletes detected
              </p>
            </div>

            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => onLoadRosterInWorkbench(players, suggestedFolder)}
              >
                <SlidersHorizontal size={14} />
                <span>Load All in Studio</span>
              </button>

              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleDownloadZip}
                disabled={downloadingZip}
              >
                <Download size={14} />
                <span>{downloadingZip ? downloadProgress : 'Export Roster (.ZIP)'}</span>
              </button>
            </div>
          </div>

          {/* Data Table */}
          <div className="table-container">
            <table className="saas-table">
              <thead>
                <tr>
                  <th style={{ width: '80px' }}>Jersey #</th>
                  <th style={{ width: '60px' }}>Photo</th>
                  <th>Athlete Name</th>
                  <th>Position</th>
                  <th style={{ textAlign: 'right', width: '130px' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {players.map((player, idx) => (
                  <tr key={idx}>
                    <td>
                      <input
                        type="text"
                        className="input-text"
                        style={{
                          width: '54px',
                          textAlign: 'center',
                          padding: '4px',
                          fontSize: '0.8125rem',
                          fontWeight: 700
                        }}
                        placeholder={player.number || `${idx + 1}`}
                        value={player.assigned_number !== undefined ? player.assigned_number : (player.number || '')}
                        onChange={(e) => handleNumberChange(idx, e.target.value)}
                      />
                    </td>
                    <td>
                      {player.image ? (
                        <img
                          src={`/api/proxy_photo?url=${encodeURIComponent(player.image)}&width=80`}
                          alt={player.name}
                          style={{
                            width: 36,
                            height: 36,
                            borderRadius: 'var(--radius-sm)',
                            objectFit: 'cover',
                            border: '1px solid var(--border)'
                          }}
                        />
                      ) : (
                        <div style={{
                          width: 36,
                          height: 36,
                          borderRadius: 'var(--radius-sm)',
                          background: 'var(--bg-subtle)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          color: 'var(--text-muted)'
                        }}>
                          <ImageIcon size={16} />
                        </div>
                      )}
                    </td>
                    <td style={{ fontWeight: 600 }}>{player.name}</td>
                    <td style={{ color: 'var(--text-secondary)' }}>
                      {player.position || player.pos || 'Athlete'}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => onTuneSingleInWorkbench(player)}
                        style={{ fontSize: '0.75rem', color: 'var(--brand)' }}
                      >
                        Tune Frame
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
