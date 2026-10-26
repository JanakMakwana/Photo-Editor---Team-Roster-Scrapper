import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Player } from '../types';
import {
  ZoomIn, ZoomOut, RotateCcw, Download, Sparkles, Sliders, Eraser,
  Brush, Image as ImageIcon, Check, Eye, ChevronLeft, ChevronRight, CheckSquare
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

  // Active athlete & photo list
  const [photos, setPhotos] = useState<Array<{ name: string; url?: string; img?: HTMLImageElement; scale: number; offset_x: number; offset_y: number }>>([]);
  const [selectedIdx, setSelectedIdx] = useState(0);

  // Transform controls
  const [scale, setScale] = useState(0.4);
  const [offsetX, setOffsetX] = useState(0);
  const [offsetY, setOffsetY] = useState(0);

  // Canvas stage state
  const [bgMode, setBgMode] = useState<'checker' | 'white' | 'dark' | 'team'>('checker');
  const [activeTool, setActiveTool] = useState<'pan' | 'erase' | 'restore'>('pan');
  const [brushSize, setBrushSize] = useState(24);
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [statusMsg, setStatusMsg] = useState('');

  // Initialize photos from props
  useEffect(() => {
    const list: typeof photos = [];
    if (initialPlayer && initialPlayer.image) {
      list.push({
        name: `${initialPlayer.name}.png`,
        url: initialPlayer.image,
        scale: 0.4,
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
            scale: 0.4,
            offset_x: 0,
            offset_y: 0
          });
        }
      });
    }

    // Default sample if empty
    if (list.length === 0) {
      list.push({
        name: 'Sample Athlete.png',
        url: '',
        scale: 0.4,
        offset_x: 0,
        offset_y: 0
      });
    }

    setPhotos(list);
    setSelectedIdx(0);
  }, [initialPlayer, rosterList]);

  // Load current photo image
  const currentPhoto = photos[selectedIdx];

  useEffect(() => {
    if (!currentPhoto) return;

    if (!currentPhoto.img) {
      const img = new Image();
      img.crossOrigin = 'anonymous';

      if (currentPhoto.url) {
        img.src = `/api/proxy_photo?url=${encodeURIComponent(currentPhoto.url)}&width=800`;
      } else {
        // Generate placeholder canvas
        const fb = document.createElement('canvas');
        fb.width = 600;
        fb.height = 600;
        const ctx = fb.getContext('2d')!;
        ctx.fillStyle = '#f1f5f9';
        ctx.fillRect(0, 0, 600, 600);
        ctx.fillStyle = '#2563eb';
        ctx.font = 'bold 80px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(currentPhoto.name.charAt(0).toUpperCase() || 'A', 300, 280);
        ctx.fillStyle = '#64748b';
        ctx.font = '600 24px sans-serif';
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
  }, [selectedIdx, currentPhoto?.url]);

  // Render Canvas
  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    // 1. Draw Background
    if (bgMode === 'white') {
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, width, height);
    } else if (bgMode === 'dark') {
      ctx.fillStyle = '#0f172a';
      ctx.fillRect(0, 0, width, height);
    } else if (bgMode === 'team') {
      ctx.fillStyle = '#002855';
      ctx.fillRect(0, 0, width, height);
    }
    // Checkerboard is handled via CSS on parent container

    // Center origin
    const centerX = width / 2;
    const centerY = height / 2;

    // 2. Draw Transformed Athlete Image
    if (currentPhoto && currentPhoto.img) {
      const img = currentPhoto.img;
      const sw = img.width * scale;
      const sh = img.height * scale;
      const dx = centerX - 90 + offsetX;
      const dy = centerY - 90 + offsetY;

      ctx.save();
      ctx.drawImage(img, dx, dy, sw, sh);
      ctx.restore();
    }

    // 3. Draw 180x180 HUD Boundary Guidelines
    ctx.save();
    const hudX = centerX - 90;
    const hudY = centerY - 90;
    const hudW = 180;
    const hudH = 180;

    // Darken exterior masking
    ctx.fillStyle = 'rgba(15, 23, 42, 0.12)';
    ctx.beginPath();
    ctx.rect(0, 0, width, height);
    ctx.rect(hudX, hudY, hudW, hudH);
    ctx.fill('evenodd');

    // Dashed boundary box
    ctx.strokeStyle = '#2563eb';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.strokeRect(hudX, hudY, hudW, hudH);

    // Rule of thirds / chin & eye reference lines
    ctx.strokeStyle = 'rgba(37, 99, 235, 0.3)';
    ctx.setLineDash([2, 4]);
    // Eye line ~35%
    ctx.beginPath();
    ctx.moveTo(hudX, hudY + hudH * 0.35);
    ctx.lineTo(hudX + hudW, hudY + hudH * 0.35);
    ctx.stroke();

    // Chin line ~75%
    ctx.beginPath();
    ctx.moveTo(hudX, hudY + hudH * 0.75);
    ctx.lineTo(hudX + hudW, hudY + hudH * 0.75);
    ctx.stroke();

    ctx.restore();
  }, [bgMode, currentPhoto, scale, offsetX, offsetY]);

  useEffect(() => {
    drawCanvas();
  }, [drawCanvas]);

  // Pan interaction
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (activeTool === 'pan') {
      setIsDragging(true);
      setDragStart({ x: e.clientX - offsetX, y: e.clientY - offsetY });
    }
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (isDragging && activeTool === 'pan') {
      const nextX = e.clientX - dragStart.x;
      const nextY = e.clientY - dragStart.y;
      setOffsetX(nextX);
      setOffsetY(nextY);
    }
  };

  const handleMouseUp = () => {
    if (isDragging) {
      setIsDragging(false);
      // Persist transform into active item
      setPhotos((prev) => {
        const next = [...prev];
        if (next[selectedIdx]) {
          next[selectedIdx] = { ...next[selectedIdx], scale, offset_x: offsetX, offset_y: offsetY };
        }
        return next;
      });
    }
  };

  const handleWheel = (e: React.WheelEvent<HTMLElement>) => {
    const delta = e.deltaY < 0 ? 0.02 : -0.02;
    const nextScale = Math.max(0.1, Math.min(2.5, scale + delta));
    setScale(nextScale);
  };

  // Automated face centering calculation
  const handleAutoAlign = async () => {
    if (!currentPhoto) return;
    setStatusMsg('Calculating face position...');

    try {
      // If photo has an image, auto-align to center standard bust
      if (currentPhoto.img) {
        const w = currentPhoto.img.width;
        const h = currentPhoto.img.height;
        const targetDim = 180 * 0.92;
        const newScale = targetDim / Math.max(w * 0.6, h * 0.6);
        const newOffX = (180 - w * newScale) / 2;
        const newOffY = 180 - h * newScale * 0.85;

        setScale(newScale);
        setOffsetX(newOffX);
        setOffsetY(newOffY);
        setStatusMsg('Framed face to 180×180 standard.');
        setTimeout(() => setStatusMsg(''), 2000);
      }
    } catch (e: any) {
      setStatusMsg(`Auto-align failed: ${e.message}`);
    }
  };

  // Export 180x180 PNG
  const handleExportPNG = () => {
    if (!currentPhoto || !currentPhoto.img) return;

    const exportCanvas = document.createElement('canvas');
    exportCanvas.width = 180;
    exportCanvas.height = 180;
    const eCtx = exportCanvas.getContext('2d')!;

    const img = currentPhoto.img;
    const sw = img.width * scale;
    const sh = img.height * scale;

    eCtx.drawImage(img, offsetX, offsetY, sw, sh);

    exportCanvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = currentPhoto.name || 'headshot_180x180.png';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 'image/png');
  };

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', textAlign: 'left' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: 20 }}>
        {/* Left: Workbench Stage */}
        <div className="stage-container">
          {/* Stage Top Toolbar */}
          <div style={{
            padding: '10px 16px',
            borderBottom: '1px solid var(--border-subtle)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: '#ffffff'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text)' }}>
                {currentPhoto?.name || 'Athlete Headshot'}
              </span>
              {statusMsg && (
                <span style={{ fontSize: '0.74rem', color: 'var(--brand-accent)', fontWeight: 600 }}>
                  &bull; {statusMsg}
                </span>
              )}
            </div>

            {/* Background Selector Chips */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 600 }}>Canvas BG:</span>
              {(['checker', 'white', 'dark', 'team'] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  className={`btn btn-sm ${bgMode === mode ? 'btn-primary' : 'btn-ghost'}`}
                  style={{ textTransform: 'capitalize', padding: '3px 8px', fontSize: '0.72rem' }}
                  onClick={() => setBgMode(mode)}
                >
                  {mode}
                </button>
              ))}
            </div>
          </div>

          {/* Canvas Interactive Viewport */}
          <div
            className={`stage-canvas-wrapper ${bgMode === 'checker' ? 'checkerboard-light' : ''}`}
            onWheel={handleWheel}
          >
            <canvas
              ref={canvasRef}
              width={700}
              height={480}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
              style={{ width: '100%', height: '100%' }}
            />
          </div>

          {/* Stage Bottom Transform Bar */}
          <div style={{
            padding: '10px 16px',
            borderTop: '1px solid var(--border-subtle)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: '#f8fafc'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <ZoomOut size={15} color="var(--text-muted)" />
                <input
                  type="range"
                  min="0.1"
                  max="1.5"
                  step="0.01"
                  value={scale}
                  onChange={(e) => setScale(parseFloat(e.target.value))}
                  style={{ width: 120, accentColor: 'var(--brand-accent)' }}
                />
                <ZoomIn size={15} color="var(--text-muted)" />
                <span style={{ fontSize: '0.76rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', width: 44 }}>
                  {Math.round(scale * 100)}%
                </span>
              </div>

              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => { setScale(0.4); setOffsetX(0); setOffsetY(0); }}
                title="Reset transform to default"
              >
                <RotateCcw size={13} />
                <span>Reset</span>
              </button>
            </div>

            <div style={{ display: 'flex', gap: 8 }}>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleAutoAlign}
              >
                <Sparkles size={14} color="#2563eb" />
                <span>Auto-Frame Face</span>
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
        </div>

        {/* Right: Tools & Filmstrip Column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Quick Specifications Card */}
          <div className="saas-card" style={{ padding: 18 }}>
            <h4 style={{ fontSize: '0.86rem', fontWeight: 800, marginBottom: 8 }}>180×180 HUD Standards</h4>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div>&bull; Top dashed line marks upper eye level.</div>
              <div>&bull; Lower dashed line marks chin clearance.</div>
              <div>&bull; Output standardizes to 180×180 transparent PNG with 0 cloud storage footprint.</div>
            </div>
          </div>

          {/* Filmstrip Carousel */}
          <div className="saas-card" style={{ padding: 18, flex: 1, display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <h4 style={{ fontSize: '0.86rem', fontWeight: 800 }}>Roster Filmstrip</h4>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 600 }}>
                {photos.length} Photo{photos.length !== 1 ? 's' : ''}
              </span>
            </div>

            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(2, 1fr)',
              gap: 8,
              maxHeight: 380,
              overflowY: 'auto'
            }}>
              {photos.map((p, idx) => {
                const active = idx === selectedIdx;
                return (
                  <div
                    key={idx}
                    onClick={() => setSelectedIdx(idx)}
                    style={{
                      border: `2px solid ${active ? 'var(--brand-accent)' : 'var(--border-subtle)'}`,
                      borderRadius: 6,
                      padding: 6,
                      background: active ? 'var(--brand-accent-subtle)' : '#ffffff',
                      cursor: 'pointer',
                      textAlign: 'center',
                      transition: 'all 0.15s ease'
                    }}
                  >
                    <div style={{
                      width: '100%',
                      height: 70,
                      background: '#f8fafc',
                      borderRadius: 4,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      overflow: 'hidden',
                      marginBottom: 4
                    }}>
                      {p.img ? (
                        <img
                          src={p.img.src}
                          alt={p.name}
                          style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                        />
                      ) : (
                        <ImageIcon size={24} color="#94a3b8" />
                      )}
                    </div>
                    <div style={{
                      fontSize: '0.7rem',
                      fontWeight: 700,
                      color: 'var(--text)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap'
                    }}>
                      {p.name.replace(/\.[^.]+$/, '')}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
