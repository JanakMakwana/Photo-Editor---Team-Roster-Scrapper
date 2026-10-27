import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Player } from '../types';
import {
  ZoomIn, ZoomOut, RotateCcw, Download, Sparkles, Image as ImageIcon,
  Check, ChevronLeft, ChevronRight, Sliders, Maximize2
} from 'lucide-react';

interface StudioWorkbenchProps {
  initialPlayer?: Player | null;
  rosterList?: Player[];
}

export const StudioWorkbench: React.FC<StudioWorkbenchProps> = ({
  initialPlayer,
  rosterList = []
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Photos list
  const [photos, setPhotos] = useState<Array<{
    name: string;
    url?: string;
    img?: HTMLImageElement;
    scale: number;
    offset_x: number;
    offset_y: number;
  }>>([]);
  const [selectedIdx, setSelectedIdx] = useState(0);

  // Transform controls
  const [scale, setScale] = useState(0.45);
  const [offsetX, setOffsetX] = useState(0);
  const [offsetY, setOffsetY] = useState(0);

  // Canvas stage state
  const [bgMode, setBgMode] = useState<'checker' | 'white' | 'dark'>('checker');
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [statusMsg, setStatusMsg] = useState('');
  const [isAligning, setIsAligning] = useState(false);

  // Stage dimensions (Fixed aspect ratio 720 x 480 to prevent canvas distortion)
  const STAGE_WIDTH = 720;
  const STAGE_HEIGHT = 480;
  const HUD_SIZE = 220; // 180x180 scaled for visual comfort

  // Initialize photos
  useEffect(() => {
    const list: typeof photos = [];

    if (initialPlayer && initialPlayer.image) {
      list.push({
        name: `${initialPlayer.name}.png`,
        url: initialPlayer.image,
        scale: 0.45,
        offset_x: 0,
        offset_y: 0
      });
    }

    if (rosterList.length > 0) {
      rosterList.forEach((p) => {
        if (p.image && (!initialPlayer || p.image !== initialPlayer.image)) {
          list.push({
            name: `${p.name}.png`,
            url: p.image,
            scale: 0.45,
            offset_x: 0,
            offset_y: 0
          });
        }
      });
    }

    if (list.length === 0) {
      list.push({
        name: 'Sample Athlete.png',
        url: '',
        scale: 0.45,
        offset_x: 0,
        offset_y: 0
      });
    }

    setPhotos(list);
    setSelectedIdx(0);
  }, [initialPlayer, rosterList]);

  const currentPhoto = photos[selectedIdx];

  // Load image object
  useEffect(() => {
    if (!currentPhoto) return;

    if (!currentPhoto.img) {
      const img = new Image();
      img.crossOrigin = 'anonymous';

      if (currentPhoto.url) {
        img.src = `/api/proxy_photo?url=${encodeURIComponent(currentPhoto.url)}&width=800`;
      } else {
        // Crisp placeholder canvas
        const fb = document.createElement('canvas');
        fb.width = 600;
        fb.height = 600;
        const ctx = fb.getContext('2d')!;
        ctx.fillStyle = '#f8fafc';
        ctx.fillRect(0, 0, 600, 600);
        ctx.fillStyle = '#2563eb';
        ctx.font = 'bold 120px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(currentPhoto.name.charAt(0).toUpperCase() || 'A', 300, 270);
        ctx.fillStyle = '#64748b';
        ctx.font = '600 24px -apple-system, sans-serif';
        ctx.fillText(currentPhoto.name.replace('.png', ''), 300, 360);
        img.src = fb.toDataURL();
      }

      img.onload = () => {
        setPhotos((prev) => {
          const next = [...prev];
          if (next[selectedIdx]) {
            next[selectedIdx] = { ...next[selectedIdx], img };
          }
          return next;
        });
      };
    } else {
      setScale(currentPhoto.scale);
      setOffsetX(currentPhoto.offset_x);
      setOffsetY(currentPhoto.offset_y);
    }
  }, [selectedIdx, currentPhoto]);

  // Main Canvas Render
  const renderCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';

    // Clear background
    ctx.clearRect(0, 0, STAGE_WIDTH, STAGE_HEIGHT);

    if (bgMode === 'white') {
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, STAGE_WIDTH, STAGE_HEIGHT);
    } else if (bgMode === 'dark') {
      ctx.fillStyle = '#0f172a';
      ctx.fillRect(0, 0, STAGE_WIDTH, STAGE_HEIGHT);
    }

    const centerX = STAGE_WIDTH / 2;
    const centerY = STAGE_HEIGHT / 2;

    // Draw athlete portrait
    if (currentPhoto && currentPhoto.img) {
      const img = currentPhoto.img;
      const w = img.width * scale;
      const h = img.height * scale;
      const x = centerX - w / 2 + offsetX;
      const y = centerY - h / 2 + offsetY;

      ctx.save();
      ctx.drawImage(img, x, y, w, h);
      ctx.restore();
    }

    // 180x180 HUD Framing Guide
    const hudX = centerX - HUD_SIZE / 2;
    const hudY = centerY - HUD_SIZE / 2;

    // Darken exterior slightly for focal concentration
    ctx.fillStyle = 'rgba(15, 23, 42, 0.18)';
    ctx.fillRect(0, 0, STAGE_WIDTH, hudY);
    ctx.fillRect(0, hudY + HUD_SIZE, STAGE_WIDTH, STAGE_HEIGHT - (hudY + HUD_SIZE));
    ctx.fillRect(0, hudY, hudX, HUD_SIZE);
    ctx.fillRect(hudX + HUD_SIZE, hudY, STAGE_WIDTH - (hudX + HUD_SIZE), HUD_SIZE);

    // Bounding Box
    ctx.strokeStyle = '#2563eb';
    ctx.lineWidth = 2;
    ctx.setLineDash([]);
    ctx.strokeRect(hudX, hudY, HUD_SIZE, HUD_SIZE);

    // Eye guideline (35% from top)
    const eyeY = hudY + HUD_SIZE * 0.35;
    ctx.strokeStyle = 'rgba(37, 99, 235, 0.65)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(hudX, eyeY);
    ctx.lineTo(hudX + HUD_SIZE, eyeY);
    ctx.stroke();

    // Chin guideline (85% from top)
    const chinY = hudY + HUD_SIZE * 0.85;
    ctx.beginPath();
    ctx.moveTo(hudX, chinY);
    ctx.lineTo(hudX + HUD_SIZE, chinY);
    ctx.stroke();

    // Vertical center crosshair
    ctx.strokeStyle = 'rgba(37, 99, 235, 0.4)';
    ctx.beginPath();
    ctx.moveTo(centerX, hudY);
    ctx.lineTo(centerX, hudY + HUD_SIZE);
    ctx.stroke();

    // HUD Label
    ctx.fillStyle = '#2563eb';
    ctx.font = '600 11px -apple-system, sans-serif';
    ctx.fillText('180 × 180 HUD FRAME', hudX + 4, hudY - 6);
  }, [currentPhoto, scale, offsetX, offsetY, bgMode]);

  useEffect(() => {
    renderCanvas();
  }, [renderCanvas]);

  // Drag and Pan
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    setIsDragging(true);
    setDragStart({ x: e.clientX - offsetX, y: e.clientY - offsetY });
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isDragging) return;
    const nextX = e.clientX - dragStart.x;
    const nextY = e.clientY - dragStart.y;
    setOffsetX(nextX);
    setOffsetY(nextY);

    setPhotos((prev) => {
      const next = [...prev];
      if (next[selectedIdx]) {
        next[selectedIdx] = { ...next[selectedIdx], offset_x: nextX, offset_y: nextY };
      }
      return next;
    });
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  // Zoom via wheel
  const handleWheel = (e: React.WheelEvent<HTMLElement>) => {
    const delta = e.deltaY < 0 ? 0.02 : -0.02;
    const nextScale = Math.max(0.1, Math.min(2.5, scale + delta));
    setScale(nextScale);

    setPhotos((prev) => {
      const next = [...prev];
      if (next[selectedIdx]) {
        next[selectedIdx] = { ...next[selectedIdx], scale: nextScale };
      }
      return next;
    });
  };

  // Auto-Align
  const handleAutoAlign = async () => {
    if (!currentPhoto) return;
    setIsAligning(true);
    setStatusMsg('Detecting face geometry...');

    try {
      const q = new URLSearchParams({ name: currentPhoto.name });
      const res = await fetch(`/api/auto_align?${q.toString()}`);
      if (res.ok) {
        const data = await res.json();
        if (data && data.scale) {
          setScale(data.scale);
          setOffsetX(data.offset_x || 0);
          setOffsetY(data.offset_y || 0);
          setStatusMsg('Face centered & framed.');
        }
      } else {
        // Fallback calculation
        setScale(0.48);
        setOffsetX(0);
        setOffsetY(-10);
        setStatusMsg('Standard portrait framing applied.');
      }
    } catch (e) {
      setScale(0.48);
      setStatusMsg('Standard portrait framing applied.');
    } finally {
      setIsAligning(false);
      setTimeout(() => setStatusMsg(''), 3000);
    }
  };

  // Export 180x180 PNG
  const handleExportPNG = () => {
    if (!currentPhoto || !currentPhoto.img) return;

    const outCanvas = document.createElement('canvas');
    outCanvas.width = 180;
    outCanvas.height = 180;
    const ctx = outCanvas.getContext('2d')!;

    const img = currentPhoto.img;
    const factor = 180 / HUD_SIZE;
    const w = img.width * scale * factor;
    const h = img.height * scale * factor;
    const x = 90 - w / 2 + offsetX * factor;
    const y = 90 - h / 2 + offsetY * factor;

    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(img, x, y, w, h);

    const link = document.createElement('a');
    link.download = currentPhoto.name.endsWith('.png') ? currentPhoto.name : `${currentPhoto.name}.png`;
    link.href = outCanvas.toDataURL('image/png');
    link.click();
    setStatusMsg('Exported 180×180 PNG.');
    setTimeout(() => setStatusMsg(''), 2500);
  };

  return (
    <div style={{ maxWidth: 1160, margin: '0 auto', textAlign: 'left' }}>
      <div className="studio-container">
        {/* Left: Interactive Stage */}
        <div className="stage-card">
          {/* Top Stage Bar */}
          <div className="stage-top-bar">
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{ fontSize: '0.875rem', fontWeight: 700, color: 'var(--text-main)' }}>
                {currentPhoto?.name || 'Athlete Headshot'}
              </span>
              {statusMsg && (
                <span style={{ fontSize: '0.75rem', color: 'var(--brand)', fontWeight: 600 }}>
                  &bull; {statusMsg}
                </span>
              )}
            </div>

            {/* Background Selector */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600 }}>BG:</span>
              <button
                type="button"
                className={`btn btn-sm ${bgMode === 'checker' ? 'btn-secondary' : 'btn-ghost'}`}
                style={{ padding: '3px 8px', fontSize: '0.75rem' }}
                onClick={() => setBgMode('checker')}
              >
                Checker
              </button>
              <button
                type="button"
                className={`btn btn-sm ${bgMode === 'white' ? 'btn-secondary' : 'btn-ghost'}`}
                style={{ padding: '3px 8px', fontSize: '0.75rem' }}
                onClick={() => setBgMode('white')}
              >
                White
              </button>
              <button
                type="button"
                className={`btn btn-sm ${bgMode === 'dark' ? 'btn-secondary' : 'btn-ghost'}`}
                style={{ padding: '3px 8px', fontSize: '0.75rem' }}
                onClick={() => setBgMode('dark')}
              >
                Dark
              </button>
            </div>
          </div>

          {/* Viewport Canvas (720 x 480 fixed aspect ratio) */}
          <div
            className={`stage-viewport ${
              bgMode === 'checker' ? 'viewport-checkerboard' : bgMode === 'white' ? 'viewport-white' : 'viewport-dark'
            }`}
            onWheel={handleWheel}
            style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
          >
            <canvas
              ref={canvasRef}
              width={STAGE_WIDTH}
              height={STAGE_HEIGHT}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
              style={{ width: '100%', height: '100%', display: 'block' }}
            />
          </div>

          {/* Bottom Stage Bar */}
          <div className="stage-bottom-bar">
            {/* Zoom Slider */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <ZoomOut size={16} color="var(--text-muted)" />
              <input
                type="range"
                min="0.1"
                max="1.5"
                step="0.01"
                value={scale}
                onChange={(e) => setScale(parseFloat(e.target.value))}
                style={{ width: 130, accentColor: 'var(--brand)' }}
              />
              <ZoomIn size={16} color="var(--text-muted)" />
              <span style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', minWidth: 42 }}>
                {Math.round(scale * 100)}%
              </span>
            </div>

            {/* Quick Actions */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => { setScale(0.45); setOffsetX(0); setOffsetY(0); }}
                title="Reset position and zoom"
              >
                <RotateCcw size={14} />
                <span>Reset</span>
              </button>

              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleAutoAlign}
                disabled={isAligning}
              >
                <Sparkles size={14} color="#2563eb" />
                <span>{isAligning ? 'Aligning...' : 'Auto-Frame Face'}</span>
              </button>

              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleExportPNG}
              >
                <Download size={14} />
                <span>Export 180×180 PNG</span>
              </button>
            </div>
          </div>

          {/* Filmstrip Reel */}
          {photos.length > 1 && (
            <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border)', background: '#f8fafc' }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '8px' }}>
                Roster Filmstrip ({photos.length} Athletes)
              </div>
              <div className="filmstrip-reel">
                {photos.map((p, idx) => (
                  <div
                    key={idx}
                    className={`filmstrip-item ${idx === selectedIdx ? 'active' : ''}`}
                    onClick={() => setSelectedIdx(idx)}
                  >
                    <img
                      src={p.url ? `/api/proxy_photo?url=${encodeURIComponent(p.url)}&width=140` : ''}
                      alt={p.name}
                      className="filmstrip-thumb"
                      onError={(e) => { (e.target as HTMLElement).style.display = 'none'; }}
                    />
                    <div className="filmstrip-name">{p.name.replace('.png', '')}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Right: Inspector / Specifications Panel */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Alignment Specifications Card */}
          <div className="card" style={{ padding: '20px' }}>
            <h4 style={{ fontSize: '0.875rem', fontWeight: 700, marginBottom: '12px' }}>
              180×180 Standard Framing
            </h4>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                <span style={{ color: 'var(--brand)', fontWeight: 700 }}>&bull;</span>
                <span>Upper dashed guideline aligns with eye level.</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                <span style={{ color: 'var(--brand)', fontWeight: 700 }}>&bull;</span>
                <span>Lower dashed line ensures chin clearance.</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                <span style={{ color: 'var(--brand)', fontWeight: 700 }}>&bull;</span>
                <span>Exports transparent 180×180 PNG compliant with HUDL standards.</span>
              </div>
            </div>
          </div>

          {/* Precision Coordinates Card */}
          <div className="card" style={{ padding: '20px' }}>
            <h4 style={{ fontSize: '0.875rem', fontWeight: 700, marginBottom: '14px' }}>
              Transform Coordinates
            </h4>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div className="form-group" style={{ margin: 0 }}>
                <label className="form-label">X Offset</label>
                <input
                  type="number"
                  className="input-text"
                  value={Math.round(offsetX)}
                  onChange={(e) => setOffsetX(parseInt(e.target.value) || 0)}
                />
              </div>
              <div className="form-group" style={{ margin: 0 }}>
                <label className="form-label">Y Offset</label>
                <input
                  type="number"
                  className="input-text"
                  value={Math.round(offsetY)}
                  onChange={(e) => setOffsetY(parseInt(e.target.value) || 0)}
                />
              </div>
            </div>
          </div>

          {/* Direct Export CTA */}
          <button
            type="button"
            className="btn btn-primary btn-lg"
            onClick={handleExportPNG}
            style={{ width: '100%', height: '46px' }}
          >
            <Download size={16} />
            <span>Download Standardized PNG</span>
          </button>
        </div>
      </div>
    </div>
  );
};
