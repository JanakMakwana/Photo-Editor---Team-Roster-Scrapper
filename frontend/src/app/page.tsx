'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Shield, User as UserIcon, Users, Building, LogOut, Search, Globe, Folder,
  Scissors, Save, Download, Sparkles, Move, Eraser, RotateCcw,
  RefreshCw, Check, ArrowLeft, ArrowRight, Table, Copy, FileSpreadsheet,
  Layers, Sliders, Eye, AlertCircle, KeyRound, HardDrive, Cpu
} from 'lucide-react';
import JSZip from 'jszip';

interface User {
  id: string;
  email: string;
  full_name: string;
  role: 'superadmin' | 'company_admin' | 'member';
  is_superadmin: boolean;
  mfa_enabled: boolean;
  company: {
    id: string;
    name: string;
    slug: string;
    plan: string;
    max_seats: number;
    used_seats: number;
    remaining_seats: number;
    status: string;
  } | null;
  platform_metrics?: {
    total_companies: number;
    total_seats_allocated: number;
    total_used_seats: number;
    total_users: number;
    superadmin_count: number;
    regular_member_count: number;
    companies: Array<{
      id: string;
      name: string;
      slug: string;
      plan: string;
      max_seats: number;
      used_seats: number;
      status: string;
      created_at: string;
    }>;
  };
}

interface Player {
  name: string;
  jersey?: string;
  assigned_number?: string;
  position?: string;
  pos?: string;
  height?: string;
  weight?: string;
  born?: string;
  birthplace?: string;
  team?: string;
  years?: string;
  image?: string;
  shoots?: string;
}

interface PhotoOption {
  team: string;
  years?: string;
  jersey?: string;
  pos?: string;
  image?: string;
  url?: string;
  height?: string;
  weight?: string;
  shoots?: string;
  born?: string;
}

interface DetectedFolder {
  name: string;
  path: string;
  count: number;
  edited: string;
}

interface ActivePhotoData {
  name: string;
  player_name?: string;
  assigned_id?: string;
  url?: string;
  proxiedUrl?: string;
  blobFile?: File;
  blobUrl?: string;
  img?: HTMLImageElement;
  cutoutImg?: HTMLImageElement;
  scale: number;
  offset_x: number;
  offset_y: number;
  hasCutout: boolean;
  maskReady: boolean;
  saved: boolean;
}

export default function StudioApp() {
  // Authentication & User State
  const [user, setUser] = useState<User | null>(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [authTab, setAuthTab] = useState<'login' | 'activate'>('login');
  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [authName, setAuthName] = useState('');
  const [authInviteToken, setAuthInviteToken] = useState('');
  const [authError, setAuthError] = useState('');
  const [authSubmitting, setAuthSubmitting] = useState(false);

  // Modals
  const [showPlatformDashboard, setShowPlatformDashboard] = useState(false);
  const [showTeamModal, setShowTeamModal] = useState(false);
  const [showSecurityModal, setShowSecurityModal] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteName, setInviteName] = useState('');
  const [inviteRole, setInviteRole] = useState<'member' | 'company_admin'>('member');
  const [inviteLink, setInviteLink] = useState('');

  // Primary Screen View: 'landing' or 'workbench'
  const [currentScreen, setCurrentScreen] = useState<'landing' | 'workbench'>('landing');

  // Landing Workflows: 'athlete' | 'url' | 'local'
  const [activeWorkflow, setActiveWorkflow] = useState<'athlete' | 'url' | 'local'>('athlete');

  // Workflow 1: Single Athlete Search State
  const [searchPlayerName, setSearchPlayerName] = useState('LeBron James');
  const [searchTeamName, setSearchTeamName] = useState('Miami Heat');
  const [searchDestinationFolder, setSearchDestinationFolder] = useState('Miami Heat - LeBron James');
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchPlayerOptions, setSearchPlayerOptions] = useState<PhotoOption[]>([]);
  const [selectedPhotoOptionIdx, setSelectedPhotoOptionIdx] = useState<number>(0);

  // Workflow 2: Team Roster URL State
  const [rosterUrl, setRosterUrl] = useState('https://www.cardiffdevils.com/team/');
  const [rosterFolder, setRosterFolder] = useState('Cardiff Devils');
  const [rosterLoading, setRosterLoading] = useState(false);
  const [rosterPlayers, setRosterPlayers] = useState<Player[]>([]);
  const [bulkPasteOpen, setBulkPasteOpen] = useState(false);
  const [bulkPasteText, setBulkPasteText] = useState('');

  // Workflow 3: Local Photo Folder State
  const [detectedFolders, setDetectedFolders] = useState<DetectedFolder[]>([]);
  const [manualPath, setManualPath] = useState('');
  const [folderLoading, setFolderLoading] = useState(false);

  // Workbench State
  const [currentFolder, setCurrentFolder] = useState('');
  const [editedFolder, setEditedFolder] = useState('');
  const [photos, setPhotos] = useState<string[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [photoDataMap, setPhotoDataMap] = useState<Record<string, ActivePhotoData>>({});
  const [toolMode, setToolMode] = useState<'frame' | 'recover' | 'erase'>('frame');
  const [brushSize, setBrushSize] = useState(24);
  const [canvasBg, setCanvasBg] = useState<'checker' | 'dark' | 'white' | 'team'>('checker');
  const [isComparingOriginal, setIsComparingOriginal] = useState(false);
  const [toastMsg, setToastMsg] = useState('');
  const [loadingOverlay, setLoadingOverlay] = useState<string | null>(null);

  // Canvas Refs
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const brushCursorRef = useRef<HTMLDivElement | null>(null);
  const maskCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const undoStackRef = useRef<ImageData[]>([]);
  const isDraggingRef = useRef(false);
  const isPaintingRef = useRef(false);
  const dragStartRef = useRef({ x: 0, y: 0 });
  const lastPaintRef = useRef({ x: 0, y: 0 });

  const CANVAS_PX = 180;
  const BUFFER_PX = 540;
  const SCALE_RATIO = BUFFER_PX / CANVAS_PX; // 3.0

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(''), 3500);
  };

  // 1. Initial Authentication Check
  const checkAuth = useCallback(async () => {
    try {
      const res = await fetch('/api/auth/me');
      const data = await res.json();
      if (res.ok && data.logged_in && data.user) {
        setUser(data.user);
        loadSuggestedFolders();
      } else {
        setUser(null);
      }
    } catch {
      setUser(null);
    } finally {
      setAuthChecking(false);
    }
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  // Load Suggested Folders
  const loadSuggestedFolders = async () => {
    try {
      const res = await fetch('/api/suggested_folders');
      if (res.ok) {
        const data = await res.json();
        setDetectedFolders(data.suggestions_data || []);
      }
    } catch (e) {
      console.warn('Could not load suggested folders:', e);
    }
  };

  // Handle Login Submission
  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthSubmitting(true);
    setAuthError('');
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: authEmail, password: authPassword })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        setUser(data.user);
        loadSuggestedFolders();
      } else {
        setAuthError(data.message || 'Invalid credentials');
      }
    } catch {
      setAuthError('Connection error to authentication server');
    } finally {
      setAuthSubmitting(false);
    }
  };

  // Handle Invite Activation
  const handleActivateInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthSubmitting(true);
    setAuthError('');
    try {
      const res = await fetch('/api/auth/activate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token: authInviteToken,
          password: authPassword,
          full_name: authName
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        setUser(data.user);
        loadSuggestedFolders();
      } else {
        setAuthError(data.message || 'Failed to activate invitation token');
      }
    } catch {
      setAuthError('Connection error to activation server');
    } finally {
      setAuthSubmitting(false);
    }
  };

  // Handle Logout
  const handleLogout = async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
    } catch (e) {
      console.error(e);
    }
    setUser(null);
    setCurrentScreen('landing');
  };

  // Free RAM & Server Storage
  const handleFreeRAM = async () => {
    setLoadingOverlay('Freeing memory and server temporary disk...');
    try {
      const res = await fetch('/api/clear_server_storage', { method: 'POST' });
      const data = await res.json();
      showToast(`Freed ${data.freed_mb || 0} MB RAM & storage!`);
    } catch {
      showToast('Error freeing memory');
    } finally {
      setLoadingOverlay(null);
    }
  };

  // Initialize Mask Canvas
  useEffect(() => {
    if (!maskCanvasRef.current) {
      const mc = document.createElement('canvas');
      mc.width = BUFFER_PX;
      mc.height = BUFFER_PX;
      const mctx = mc.getContext('2d');
      if (mctx) {
        mctx.fillStyle = '#ffffff';
        mctx.fillRect(0, 0, BUFFER_PX, BUFFER_PX);
      }
      maskCanvasRef.current = mc;
    }
  }, [BUFFER_PX]);

  // Redraw Canvas
  const redrawCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, BUFFER_PX, BUFFER_PX);
    const activePhoto = photos[currentIndex];
    const data = photoDataMap[activePhoto];
    if (!data || !data.img) return;

    const dw = data.img.width * data.scale * SCALE_RATIO;
    const dh = data.img.height * data.scale * SCALE_RATIO;
    const dx = data.offset_x * SCALE_RATIO;
    const dy = data.offset_y * SCALE_RATIO;

    if (isComparingOriginal) {
      ctx.drawImage(data.img, dx, dy, dw, dh);
    } else {
      ctx.save();
      ctx.drawImage(data.img, dx, dy, dw, dh);
      ctx.globalCompositeOperation = 'destination-in';
      if (maskCanvasRef.current) {
        ctx.drawImage(maskCanvasRef.current, 0, 0);
      }
      ctx.restore();
    }
  }, [photos, currentIndex, photoDataMap, isComparingOriginal, BUFFER_PX, SCALE_RATIO]);

  useEffect(() => {
    redrawCanvas();
  }, [redrawCanvas]);

  // Load and auto-align selected photo
  const selectPhotoByIndex = async (index: number) => {
    if (index < 0 || index >= photos.length) return;
    setCurrentIndex(index);
    const photoName = photos[index];
    const data = photoDataMap[photoName];
    if (!data) return;

    setLoadingOverlay('Preparing portrait in studio...');
    try {
      if (!data.img) {
        const img = new Image();
        img.crossOrigin = 'anonymous';
        const loadPromise = new Promise<HTMLImageElement>((resolve, reject) => {
          img.onload = () => resolve(img);
          img.onerror = () => reject(new Error('Image failed to load'));
        });

        if (data.blobUrl) {
          img.src = data.blobUrl;
        } else if (data.proxiedUrl) {
          img.src = data.proxiedUrl;
        } else if (data.url) {
          img.src = `/api/proxy_photo?url=${encodeURIComponent(data.url)}&width=800`;
        } else {
          img.src = `/api/proxy_photo?url=${encodeURIComponent(photoName)}&width=800`;
        }

        try {
          await loadPromise;
          data.img = img;
        } catch {
          // Fallback avatar canvas
          const fbCanvas = document.createElement('canvas');
          fbCanvas.width = 600;
          fbCanvas.height = 600;
          const fbCtx = fbCanvas.getContext('2d')!;
          fbCtx.fillStyle = '#1e293b';
          fbCtx.fillRect(0, 0, 600, 600);
          fbCtx.fillStyle = '#3b82f6';
          fbCtx.font = 'bold 96px system-ui';
          fbCtx.textAlign = 'center';
          fbCtx.textBaseline = 'middle';
          fbCtx.fillText(photoName.slice(0, 2).toUpperCase(), 300, 270);
          fbCtx.fillStyle = '#94a3b8';
          fbCtx.font = '600 24px system-ui';
          fbCtx.fillText(photoName.replace('.png', ''), 300, 360);
          const fbImg = new Image();
          fbImg.src = fbCanvas.toDataURL();
          await new Promise(r => { fbImg.onload = r; });
          data.img = fbImg;
        }

        // Auto-align Face
        try {
          let autoRes: Response | null = null;
          if (data.url) {
            autoRes = await fetch('/api/auto_align', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ url: data.url })
            });
          }
          if (autoRes && autoRes.ok) {
            const autoData = await autoRes.json();
            data.scale = autoData.scale;
            data.offset_x = autoData.offset_x;
            data.offset_y = autoData.offset_y;
          } else {
            const w = data.img.width || 800;
            const h = data.img.height || 800;
            data.scale = 180 / h;
            data.offset_x = (180 - w * data.scale) / 2;
            data.offset_y = 0;
          }
        } catch {
          const w = data.img.width || 800;
          const h = data.img.height || 800;
          data.scale = 180 / h;
          data.offset_x = (180 - w * data.scale) / 2;
          data.offset_y = 0;
        }
      }

      // Reset mask to full visible
      if (maskCanvasRef.current) {
        const mctx = maskCanvasRef.current.getContext('2d');
        if (mctx) {
          mctx.fillStyle = '#ffffff';
          mctx.fillRect(0, 0, BUFFER_PX, BUFFER_PX);
        }
      }
      undoStackRef.current = [];

      setPhotoDataMap(prev => ({ ...prev, [photoName]: { ...data } }));
    } finally {
      setLoadingOverlay(null);
    }
  };

  // Perform AI Cutout on Current Photo
  const handleCutout = async () => {
    const photoName = photos[currentIndex];
    const data = photoDataMap[photoName];
    if (!data || !data.img) return;

    setLoadingOverlay('Running AI Background Removal (u2net / rembg)...');
    try {
      // Export current image on an offscreen canvas to base64
      const offCanvas = document.createElement('canvas');
      offCanvas.width = data.img.width;
      offCanvas.height = data.img.height;
      const offCtx = offCanvas.getContext('2d');
      if (!offCtx) return;
      offCtx.drawImage(data.img, 0, 0);
      const b64 = offCanvas.toDataURL('image/png');

      const res = await fetch('/api/cutout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_base64: b64 })
      });
      const resData = await res.json();
      if (res.ok && resData.status === 'ok' && resData.image_base64) {
        const cutoutImg = new Image();
        cutoutImg.crossOrigin = 'anonymous';
        await new Promise(r => {
          cutoutImg.onload = r;
          cutoutImg.src = resData.image_base64;
        });

        // Initialize mask from cutout alpha
        if (maskCanvasRef.current) {
          const mctx = maskCanvasRef.current.getContext('2d');
          if (mctx) {
            mctx.clearRect(0, 0, BUFFER_PX, BUFFER_PX);
            const dw = cutoutImg.width * data.scale * SCALE_RATIO;
            const dh = cutoutImg.height * data.scale * SCALE_RATIO;
            const dx = data.offset_x * SCALE_RATIO;
            const dy = data.offset_y * SCALE_RATIO;
            mctx.drawImage(cutoutImg, dx, dy, dw, dh);
          }
        }

        data.hasCutout = true;
        data.cutoutImg = cutoutImg;
        setPhotoDataMap(prev => ({ ...prev, [photoName]: { ...data } }));
        showToast('AI Cutout applied! You can now refine details using Recover or Erase brushes.');
      } else {
        showToast(resData.message || 'Cutout failed', );
      }
    } catch (e: unknown) {
      const err = e as Error;
      showToast('Cutout error: ' + err.message);
    } finally {
      setLoadingOverlay(null);
    }
  };

  // Auto-align Current Photo
  const handleAutoAlignCurrent = async () => {
    const photoName = photos[currentIndex];
    const data = photoDataMap[photoName];
    if (!data || !data.img) return;

    setLoadingOverlay('Detecting face & centering...');
    try {
      let res: Response | null = null;
      if (data.url) {
        res = await fetch('/api/auto_align', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: data.url })
        });
      }
      if (res && res.ok) {
        const autoData = await res.json();
        data.scale = autoData.scale;
        data.offset_x = autoData.offset_x;
        data.offset_y = autoData.offset_y;
        setPhotoDataMap(prev => ({ ...prev, [photoName]: { ...data } }));
        showToast('Face centered with 35% eye line & 85% chin clearance!');
      } else {
        showToast('Face alignment completed');
      }
    } catch {
      showToast('Could not auto-align face');
    } finally {
      setLoadingOverlay(null);
    }
  };

  // Fit Width / Height / Center
  const handleFitWidth = () => {
    const photoName = photos[currentIndex];
    const data = photoDataMap[photoName];
    if (!data || !data.img) return;
    data.scale = 180 / data.img.width;
    data.offset_x = 0;
    data.offset_y = (180 - data.img.height * data.scale) / 2;
    setPhotoDataMap(prev => ({ ...prev, [photoName]: { ...data } }));
  };

  const handleFitHeight = () => {
    const photoName = photos[currentIndex];
    const data = photoDataMap[photoName];
    if (!data || !data.img) return;
    data.scale = 180 / data.img.height;
    data.offset_x = (180 - data.img.width * data.scale) / 2;
    data.offset_y = 0;
    setPhotoDataMap(prev => ({ ...prev, [photoName]: { ...data } }));
  };

  const handleCenter = () => {
    const photoName = photos[currentIndex];
    const data = photoDataMap[photoName];
    if (!data || !data.img) return;
    data.offset_x = (180 - data.img.width * data.scale) / 2;
    data.offset_y = (180 - data.img.height * data.scale) / 2;
    setPhotoDataMap(prev => ({ ...prev, [photoName]: { ...data } }));
  };

  // Apply Framing to All
  const handleApplyFramingToAll = () => {
    const photoName = photos[currentIndex];
    const active = photoDataMap[photoName];
    if (!active) return;
    const updated = { ...photoDataMap };
    photos.forEach(name => {
      if (updated[name]) {
        updated[name].scale = active.scale;
        updated[name].offset_x = active.offset_x;
        updated[name].offset_y = active.offset_y;
      }
    });
    setPhotoDataMap(updated);
    showToast(`Applied framing across all ${photos.length} portraits in roster!`);
  };

  // Save Active Photo as 180x180 PNG
  const handleSaveActivePhoto = async () => {
    const photoName = photos[currentIndex];
    const data = photoDataMap[photoName];
    if (!data || !data.img) return;

    // Render precise 180x180 export canvas
    const exportCanvas = document.createElement('canvas');
    exportCanvas.width = CANVAS_PX;
    exportCanvas.height = CANVAS_PX;
    const expCtx = exportCanvas.getContext('2d');
    if (!expCtx) return;

    const dw = data.img.width * data.scale;
    const dh = data.img.height * data.scale;
    const dx = data.offset_x;
    const dy = data.offset_y;

    expCtx.drawImage(data.img, dx, dy, dw, dh);
    if (!isComparingOriginal && maskCanvasRef.current) {
      expCtx.globalCompositeOperation = 'destination-in';
      expCtx.drawImage(maskCanvasRef.current, 0, 0, BUFFER_PX, BUFFER_PX, 0, 0, CANVAS_PX, CANVAS_PX);
    }

    const b64 = exportCanvas.toDataURL('image/png');
    // Save to disk or download directly
    try {
      const res = await fetch('/api/save_photo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          folder: currentFolder || 'Exported_Headshots',
          name: photoName,
          image_base64: b64
        })
      });
      if (res.ok) {
        data.saved = true;
        setPhotoDataMap(prev => ({ ...prev, [photoName]: { ...data } }));
        showToast(`Saved ${photoName} (180×180 PNG)!`);
      } else {
        // Trigger browser download directly
        const a = document.createElement('a');
        a.href = b64;
        a.download = photoName;
        a.click();
        data.saved = true;
        setPhotoDataMap(prev => ({ ...prev, [photoName]: { ...data } }));
        showToast(`Downloaded ${photoName} (180×180 PNG)!`);
      }
    } catch {
      const a = document.createElement('a');
      a.href = b64;
      a.download = photoName;
      a.click();
      data.saved = true;
      setPhotoDataMap(prev => ({ ...prev, [photoName]: { ...data } }));
      showToast(`Downloaded ${photoName}!`);
    }
  };

  // Download All as ZIP
  const handleDownloadAllZip = async () => {
    setLoadingOverlay('Generating standardized 180×180 ZIP package...');
    try {
      const zip = new JSZip();
      const folderName = (currentFolder || 'Athletes').replace(/[^a-zA-Z0-9_\-\s]/g, '').trim() || 'Athletes';
      const rootFolder = zip.folder(folderName) || zip;

      for (let i = 0; i < photos.length; i++) {
        const pName = photos[i];
        const pData = photoDataMap[pName];
        if (!pData) continue;

        let imgToRender = pData.img;
        if (!imgToRender) {
          const img = new Image();
          img.crossOrigin = 'anonymous';
          const p = new Promise(r => { img.onload = r; img.onerror = r; });
          img.src = pData.proxiedUrl || pData.url || '';
          await p;
          imgToRender = img;
        }

        const expCanvas = document.createElement('canvas');
        expCanvas.width = CANVAS_PX;
        expCanvas.height = CANVAS_PX;
        const eCtx = expCanvas.getContext('2d');
        if (eCtx && imgToRender) {
          const dw = imgToRender.width * pData.scale;
          const dh = imgToRender.height * pData.scale;
          const dx = pData.offset_x;
          const dy = pData.offset_y;
          eCtx.drawImage(imgToRender, dx, dy, dw, dh);
        }

        const b64 = expCanvas.toDataURL('image/png').split(',')[1];
        rootFolder.file(pName.endsWith('.png') ? pName : `${pName}.png`, b64, { base64: true });
      }

      const zipBlob = await zip.generateAsync({ type: 'blob' });
      const dlUrl = URL.createObjectURL(zipBlob);
      const a = document.createElement('a');
      a.href = dlUrl;
      a.download = `${folderName}_180x180.zip`;
      a.click();
      URL.revokeObjectURL(dlUrl);
      showToast(`Downloaded ${photos.length} headshots in standardized ZIP!`);
    } catch (e: unknown) {
      const err = e as Error;
      showToast('Error generating ZIP: ' + err.message);
    } finally {
      setLoadingOverlay(null);
    }
  };

  // Brush Painting Handlers
  const handleCanvasMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const rect = viewport.getBoundingClientRect();
    const clientX = e.clientX - rect.left;
    const clientY = e.clientY - rect.top;
    const canvasX = (clientX / rect.width) * BUFFER_PX;
    const canvasY = (clientY / rect.height) * BUFFER_PX;

    if (toolMode === 'frame') {
      isDraggingRef.current = true;
      dragStartRef.current = { x: e.clientX, y: e.clientY };
    } else {
      isPaintingRef.current = true;
      lastPaintRef.current = { x: canvasX, y: canvasY };
      saveUndoState();
      paintStroke(canvasX, canvasY);
    }
  };

  const handleCanvasMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const rect = viewport.getBoundingClientRect();

    // Update brush cursor
    if (brushCursorRef.current) {
      if (toolMode !== 'frame') {
        const sizePx = brushSize * 2 * (rect.width / BUFFER_PX);
        brushCursorRef.current.style.display = 'block';
        brushCursorRef.current.style.width = `${sizePx}px`;
        brushCursorRef.current.style.height = `${sizePx}px`;
        brushCursorRef.current.style.left = `${e.clientX - rect.left}px`;
        brushCursorRef.current.style.top = `${e.clientY - rect.top}px`;
      } else {
        brushCursorRef.current.style.display = 'none';
      }
    }

    if (isDraggingRef.current && toolMode === 'frame') {
      const dx = ((e.clientX - dragStartRef.current.x) / rect.width) * CANVAS_PX;
      const dy = ((e.clientY - dragStartRef.current.y) / rect.height) * CANVAS_PX;
      dragStartRef.current = { x: e.clientX, y: e.clientY };

      const activePhoto = photos[currentIndex];
      const data = photoDataMap[activePhoto];
      if (data) {
        data.offset_x += dx;
        data.offset_y += dy;
        setPhotoDataMap(prev => ({ ...prev, [activePhoto]: { ...data } }));
      }
    } else if (isPaintingRef.current && toolMode !== 'frame') {
      const clientX = e.clientX - rect.left;
      const clientY = e.clientY - rect.top;
      const canvasX = (clientX / rect.width) * BUFFER_PX;
      const canvasY = (clientY / rect.height) * BUFFER_PX;
      paintLine(lastPaintRef.current.x, lastPaintRef.current.y, canvasX, canvasY);
      lastPaintRef.current = { x: canvasX, y: canvasY };
    }
  };

  const handleCanvasMouseUp = () => {
    isDraggingRef.current = false;
    isPaintingRef.current = false;
  };

  const handleCanvasWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    if (toolMode !== 'frame') return;
    e.preventDefault();
    const viewport = viewportRef.current;
    if (!viewport) return;
    const rect = viewport.getBoundingClientRect();
    const mouseX = ((e.clientX - rect.left) / rect.width) * CANVAS_PX;
    const mouseY = ((e.clientY - rect.top) / rect.height) * CANVAS_PX;

    const zoomFactor = e.deltaY < 0 ? 1.06 : 0.94;
    const activePhoto = photos[currentIndex];
    const data = photoDataMap[activePhoto];
    if (!data || !data.img) return;

    const oldScale = data.scale;
    const newScale = Math.max(0.05, Math.min(2.0, oldScale * zoomFactor));

    data.offset_x = mouseX - (mouseX - data.offset_x) * (newScale / oldScale);
    data.offset_y = mouseY - (mouseY - data.offset_y) * (newScale / oldScale);
    data.scale = newScale;

    setPhotoDataMap(prev => ({ ...prev, [activePhoto]: { ...data } }));
  };

  const saveUndoState = () => {
    if (!maskCanvasRef.current) return;
    const mctx = maskCanvasRef.current.getContext('2d');
    if (!mctx) return;
    const snapshot = mctx.getImageData(0, 0, BUFFER_PX, BUFFER_PX);
    undoStackRef.current.push(snapshot);
    if (undoStackRef.current.length > 20) {
      undoStackRef.current.shift();
    }
  };

  const handleUndoMask = () => {
    if (undoStackRef.current.length === 0 || !maskCanvasRef.current) return;
    const mctx = maskCanvasRef.current.getContext('2d');
    if (!mctx) return;
    const previous = undoStackRef.current.pop();
    if (previous) {
      mctx.putImageData(previous, 0, 0);
      redrawCanvas();
      showToast('Undid brush stroke');
    }
  };

  const handleResetMask = () => {
    const photoName = photos[currentIndex];
    const data = photoDataMap[photoName];
    if (!data || !maskCanvasRef.current) return;
    const mctx = maskCanvasRef.current.getContext('2d');
    if (!mctx) return;

    if (data.hasCutout && data.cutoutImg) {
      mctx.clearRect(0, 0, BUFFER_PX, BUFFER_PX);
      const dw = data.cutoutImg.width * data.scale * SCALE_RATIO;
      const dh = data.cutoutImg.height * data.scale * SCALE_RATIO;
      const dx = data.offset_x * SCALE_RATIO;
      const dy = data.offset_y * SCALE_RATIO;
      mctx.drawImage(data.cutoutImg, dx, dy, dw, dh);
    } else {
      mctx.fillStyle = '#ffffff';
      mctx.fillRect(0, 0, BUFFER_PX, BUFFER_PX);
    }
    redrawCanvas();
    showToast('Cutout mask reset');
  };

  const paintStroke = (x: number, y: number) => {
    if (!maskCanvasRef.current) return;
    const mctx = maskCanvasRef.current.getContext('2d');
    if (!mctx) return;
    mctx.save();
    mctx.beginPath();
    mctx.arc(x, y, brushSize, 0, Math.PI * 2);
    if (toolMode === 'recover') {
      mctx.globalCompositeOperation = 'source-over';
      mctx.fillStyle = '#ffffff';
    } else if (toolMode === 'erase') {
      mctx.globalCompositeOperation = 'destination-out';
      mctx.fillStyle = '#000000';
    }
    mctx.fill();
    mctx.restore();
    redrawCanvas();
  };

  const paintLine = (x1: number, y1: number, x2: number, y2: number) => {
    if (!maskCanvasRef.current) return;
    const mctx = maskCanvasRef.current.getContext('2d');
    if (!mctx) return;
    mctx.save();
    mctx.beginPath();
    mctx.moveTo(x1, y1);
    mctx.lineTo(x2, y2);
    mctx.lineWidth = brushSize * 2;
    mctx.lineCap = 'round';
    mctx.lineJoin = 'round';
    if (toolMode === 'recover') {
      mctx.globalCompositeOperation = 'source-over';
      mctx.strokeStyle = '#ffffff';
    } else if (toolMode === 'erase') {
      mctx.globalCompositeOperation = 'destination-out';
      mctx.strokeStyle = '#000000';
    }
    mctx.stroke();
    mctx.restore();
    redrawCanvas();
  };

  // Keyboard navigation for carousel
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return;
      if (currentScreen === 'workbench') {
        if (e.key === 'ArrowLeft') {
          e.preventDefault();
          selectPhotoByIndex((currentIndex - 1 + photos.length) % photos.length);
        } else if (e.key === 'ArrowRight') {
          e.preventDefault();
          selectPhotoByIndex((currentIndex + 1) % photos.length);
        } else if (e.key === ' ') {
          e.preventDefault();
          setIsComparingOriginal(true);
        }
      }
    };
    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.key === ' ') {
        setIsComparingOriginal(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
    };
  }, [currentScreen, currentIndex, photos.length]);

  // Workflow 1: Single Athlete Search Action
  const handleSearchAthlete = async () => {
    if (!searchPlayerName.trim()) return;
    setSearchLoading(true);
    try {
      const res = await fetch('/api/fetch_roster', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          player_name: searchPlayerName,
          team_name: searchTeamName
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        if (data.photo_options && data.photo_options.length > 0) {
          setSearchPlayerOptions(data.photo_options);
          setSelectedPhotoOptionIdx(0);
        } else if (data.players && data.players.length > 0) {
          // Direct player found
          setSearchPlayerOptions(data.players);
          setSelectedPhotoOptionIdx(0);
        } else {
          showToast('No high-res athlete portraits found for this stint');
        }
      } else {
        showToast(data.message || 'Search failed');
      }
    } catch {
      showToast('Search request error');
    } finally {
      setSearchLoading(false);
    }
  };

  // Load Single Athlete into Studio Workbench
  const loadSingleAthleteIntoStudio = async () => {
    const selected = searchPlayerOptions[selectedPhotoOptionIdx];
    if (!selected || !selected.image) {
      showToast('Please select a valid athlete portrait');
      return;
    }

    const folderName = searchDestinationFolder || `${searchPlayerName} (${searchTeamName || 'Career'})`;
    const photoFileName = `${searchPlayerName.replace(/[^a-zA-Z0-9_\-\s]/g, '').trim()}.png`;
    const proxied = `/api/proxy_photo?url=${encodeURIComponent(selected.image)}&width=800`;

    const initialMap: Record<string, ActivePhotoData> = {
      [photoFileName]: {
        name: photoFileName,
        player_name: searchPlayerName,
        url: selected.image,
        proxiedUrl: proxied,
        scale: 0.45,
        offset_x: 0,
        offset_y: 0,
        hasCutout: false,
        maskReady: false,
        saved: false
      }
    };

    setCurrentFolder(folderName);
    setEditedFolder(`${folderName}_edited`);
    setPhotos([photoFileName]);
    setPhotoDataMap(initialMap);
    setCurrentIndex(0);
    setCurrentScreen('workbench');
    await selectPhotoByIndex(0);
  };

  // Workflow 2: Fetch Team Roster Action
  const handleFetchTeamRoster = async () => {
    if (!rosterUrl.trim()) return;
    setRosterLoading(true);
    try {
      const res = await fetch('/api/fetch_roster', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: rosterUrl })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok' && data.players) {
        setRosterPlayers(data.players);
        if (data.suggested_folder) {
          setRosterFolder(data.suggested_folder);
        }
        showToast(`Fetched ${data.players.length} players from team website!`);
      } else {
        showToast(data.message || 'Could not scrape roster from URL');
      }
    } catch {
      showToast('Roster scrape network error');
    } finally {
      setRosterLoading(false);
    }
  };

  // Load Team Roster directly into Studio Workbench
  const loadTeamRosterIntoStudio = async () => {
    const validPlayers = rosterPlayers.filter(p => p.image && p.image.trim());
    if (validPlayers.length === 0) {
      showToast('No player portraits available to tune in Studio');
      return;
    }

    const map: Record<string, ActivePhotoData> = {};
    const photoNames: string[] = [];

    validPlayers.forEach((p, idx) => {
      const assigned = p.assigned_number ? p.assigned_number.trim() : (p.jersey || '');
      const cleanAssigned = assigned.replace(/[\\/*?:"<>|]/g, '').trim();
      const cleanName = (p.name || `Player_${idx + 1}`).replace(/[\\/*?:"<>|]/g, '').trim();
      const filename = cleanAssigned ? `${cleanAssigned}.png` : `${cleanName}.png`;
      const proxied = `/api/proxy_photo?url=${encodeURIComponent(p.image!)}&width=800`;

      photoNames.push(filename);
      map[filename] = {
        name: filename,
        player_name: p.name,
        assigned_id: cleanAssigned,
        url: p.image,
        proxiedUrl: proxied,
        scale: 0.45,
        offset_x: 0,
        offset_y: 0,
        hasCutout: false,
        maskReady: false,
        saved: false
      };
    });

    setCurrentFolder(rosterFolder || 'Team_Roster');
    setEditedFolder(`${rosterFolder || 'Team_Roster'}_edited`);
    setPhotos(photoNames);
    setPhotoDataMap(map);
    setCurrentIndex(0);
    setCurrentScreen('workbench');
    await selectPhotoByIndex(0);
  };

  // Workflow 3: Open Local Folder
  const handleOpenLocalFolder = async (folderPath: string) => {
    setFolderLoading(true);
    setLoadingOverlay('Scanning local photo folder...');
    try {
      const res = await fetch('/api/open_folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: folderPath })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok' && data.photos && data.photos.length > 0) {
        const map: Record<string, ActivePhotoData> = {};
        const photoNames: string[] = [];

        data.photos.forEach((p: { name: string; path: string; is_saved: boolean }) => {
          photoNames.push(p.name);
          map[p.name] = {
            name: p.name,
            url: p.path,
            scale: 0.45,
            offset_x: 0,
            offset_y: 0,
            hasCutout: false,
            maskReady: false,
            saved: p.is_saved
          };
        });

        setCurrentFolder(data.folder);
        setEditedFolder(data.edited_folder);
        setPhotos(photoNames);
        setPhotoDataMap(map);
        setCurrentIndex(0);
        setCurrentScreen('workbench');
        await selectPhotoByIndex(0);
      } else {
        showToast(data.message || 'No photos found in folder');
      }
    } catch {
      showToast('Could not open folder');
    } finally {
      setFolderLoading(false);
      setLoadingOverlay(null);
    }
  };

  // Native Folder Picker
  const handleNativeFolderPicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    const imgFiles = files.filter(f => /\.(png|jpe?g|webp)$/i.test(f.name));
    if (imgFiles.length === 0) {
      showToast('No image files found in folder');
      return;
    }

    const folderName = files[0].webkitRelativePath ? files[0].webkitRelativePath.split('/')[0] : 'Selected_Photos';
    const map: Record<string, ActivePhotoData> = {};
    const photoNames: string[] = [];

    imgFiles.forEach(f => {
      const blobUrl = URL.createObjectURL(f);
      photoNames.push(f.name);
      map[f.name] = {
        name: f.name,
        blobFile: f,
        blobUrl: blobUrl,
        scale: 0.45,
        offset_x: 0,
        offset_y: 0,
        hasCutout: false,
        maskReady: false,
        saved: false
      };
    });

    setCurrentFolder(folderName);
    setEditedFolder(`${folderName}_edited`);
    setPhotos(photoNames);
    setPhotoDataMap(map);
    setCurrentIndex(0);
    setCurrentScreen('workbench');
    selectPhotoByIndex(0);
  };

  // Copy Roster for Google Sheets
  const handleCopyForSheets = () => {
    if (rosterPlayers.length === 0) return;
    const headers = ['Player Name', 'Jersey #', 'Assigned ID', 'Position', 'Height', 'Weight', 'Born', 'Filename'];
    const rows = rosterPlayers.map((p, idx) => [
      p.name || '',
      p.jersey || '',
      p.assigned_number || '',
      p.position || p.pos || '',
      p.height || '',
      p.weight || '',
      p.born || '',
      p.assigned_number ? `${p.assigned_number}.png` : `${p.name || idx + 1}.png`
    ]);
    const tsv = [headers.join('\t'), ...rows.map(r => r.join('\t'))].join('\n');
    navigator.clipboard.writeText(tsv);
    showToast('Copied roster data formatted for Google Sheets & Excel!');
  };

  // Apply Bulk Paste IDs
  const handleApplyBulkPaste = () => {
    if (!bulkPasteText.trim()) return;
    const lines = bulkPasteText.trim().split('\n');
    const updated = [...rosterPlayers];

    lines.forEach((line, idx) => {
      if (idx >= updated.length) return;
      const parts = line.split('\t');
      const val = (parts.length > 1 ? parts[1] : parts[0]).trim();
      if (val) {
        updated[idx] = { ...updated[idx], assigned_number: val };
      }
    });

    setRosterPlayers(updated);
    setBulkPasteOpen(false);
    showToast('Applied assigned IDs across roster table!');
  };

  // ==========================================
  // RENDER: Authentication Gateway
  // ==========================================
  if (authChecking) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#080c14' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
          <div style={{ width: 44, height: 44, borderRadius: 12, background: 'linear-gradient(135deg, #3b82f6, #1d4ed8)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 24px rgba(59,130,246,0.5)' }}>
            <Cpu size={24} color="#fff" />
          </div>
          <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#94a3b8' }}>Initializing VeloRoster Pro...</div>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'radial-gradient(ellipse at 50% 20%, #0f1c38 0%, #080c14 70%)', padding: 24 }}>
        <div className="designer-card" style={{ maxWidth: 440, width: '100%', padding: '36px 32px' }}>
          {/* Brand Heading */}
          <div style={{ textAlign: 'center', marginBottom: 28 }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 48, height: 48, borderRadius: 14, background: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)', boxShadow: '0 8px 24px rgba(37,99,235,0.4)', marginBottom: 16 }}>
              <Shield size={24} color="#ffffff" />
            </div>
            <h1 style={{ fontSize: '1.4rem', fontWeight: 800, color: '#f8fafc', letterSpacing: '-0.02em' }}>
              VeloRoster <span style={{ color: '#3b82f6' }}>Pro</span>
            </h1>
            <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.08em', marginTop: 4 }}>
              Athletic Roster & 180×180 Studio
            </div>
          </div>

          {/* Auth Mode Switch */}
          <div style={{ display: 'flex', background: 'rgba(15, 23, 42, 0.6)', padding: 3, borderRadius: 10, marginBottom: 24 }}>
            <button
              type="button"
              className="btn-designer"
              style={{ flex: 1, padding: '7px 0', borderRadius: 8, background: authTab === 'login' ? 'rgba(255,255,255,0.1)' : 'transparent', color: authTab === 'login' ? '#fff' : '#64748b' }}
              onClick={() => setAuthTab('login')}
            >
              Sign In
            </button>
            <button
              type="button"
              className="btn-designer"
              style={{ flex: 1, padding: '7px 0', borderRadius: 8, background: authTab === 'activate' ? 'rgba(255,255,255,0.1)' : 'transparent', color: authTab === 'activate' ? '#fff' : '#64748b' }}
              onClick={() => setAuthTab('activate')}
            >
              Activate Seat
            </button>
          </div>

          {authError && (
            <div style={{ padding: '10px 14px', background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, color: '#fca5a5', fontSize: '0.8125rem', marginBottom: 18, display: 'flex', alignItems: 'center', gap: 8 }}>
              <AlertCircle size={16} />
              <span>{authError}</span>
            </div>
          )}

          {authTab === 'login' ? (
            <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', marginBottom: 6 }}>Corporate Email or Username</label>
                <input
                  type="text"
                  className="designer-input"
                  placeholder="enterprise@ecstaticloud.com or name@company.com"
                  value={authEmail}
                  onChange={e => setAuthEmail(e.target.value)}
                  required
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', marginBottom: 6 }}>Password</label>
                <input
                  type="password"
                  className="designer-input"
                  placeholder="••••••••"
                  value={authPassword}
                  onChange={e => setAuthPassword(e.target.value)}
                  required
                />
              </div>
              <button
                type="submit"
                disabled={authSubmitting}
                className="btn-designer btn-designer-primary"
                style={{ padding: '12px 0', marginTop: 8 }}
              >
                {authSubmitting ? 'Authenticating...' : 'Enter Studio Workspace'}
              </button>
              <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.75rem', color: '#64748b' }}>Account:</span>
                <button
                  type="button"
                  className="btn-designer btn-designer-secondary"
                  style={{ fontSize: '0.72rem', padding: '4px 10px' }}
                  onClick={() => {
                    setAuthEmail('enterprise@ecstaticloud.com');
                  }}
                >
                  Fill Email (enterprise@ecstaticloud.com)
                </button>
              </div>
            </form>
          ) : (
            <form onSubmit={handleActivateInvite} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', marginBottom: 6 }}>Invitation Token</label>
                <input
                  type="text"
                  className="designer-input"
                  placeholder="Paste 32-character invite token"
                  value={authInviteToken}
                  onChange={e => setAuthInviteToken(e.target.value)}
                  required
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', marginBottom: 6 }}>Your Full Name</label>
                <input
                  type="text"
                  className="designer-input"
                  placeholder="Coach Sarah Jenkins"
                  value={authName}
                  onChange={e => setAuthName(e.target.value)}
                  required
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', marginBottom: 6 }}>Create Password</label>
                <input
                  type="password"
                  className="designer-input"
                  placeholder="Minimum 6 characters"
                  value={authPassword}
                  onChange={e => setAuthPassword(e.target.value)}
                  required
                />
              </div>
              <button
                type="submit"
                disabled={authSubmitting}
                className="btn-designer btn-designer-primary"
                style={{ padding: '12px 0', marginTop: 6 }}
              >
                {authSubmitting ? 'Activating...' : 'Activate Seat & Open Studio'}
              </button>
            </form>
          )}

          <div style={{ marginTop: 24, fontSize: '0.7rem', color: '#475569', textAlign: 'center', lineHeight: 1.5 }}>
            Ecstaticloud Technologies &bull; Commercial Edition &bull; 0 Cloud Storage
          </div>
        </div>
      </div>
    );
  }

  // ==========================================
  // RENDER: Authenticated Application
  // ==========================================
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-app)' }}>
      {/* Toast Notification */}
      {toastMsg && (
        <div className="designer-toast">
          <Sparkles size={16} color="#3b82f6" />
          <span>{toastMsg}</span>
        </div>
      )}

      {/* Loading Overlay */}
      {loadingOverlay && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(8,12,20,0.85)', backdropFilter: 'blur(8px)', zIndex: 99999, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 14 }}>
          <div style={{ width: 40, height: 40, border: '3px solid rgba(59,130,246,0.2)', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
          <div style={{ fontSize: '0.9rem', fontWeight: 600, color: '#f8fafc' }}>{loadingOverlay}</div>
          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      )}

      {/* Top Navbar */}
      <header style={{ height: 60, borderBottom: '1px solid var(--border-subtle)', background: 'rgba(13,19,31,0.85)', backdropFilter: 'blur(16px)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px', position: 'sticky', top: 0, zIndex: 50 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
          {/* Brand */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }} onClick={() => setCurrentScreen('landing')}>
            <div style={{ width: 32, height: 32, borderRadius: 8, background: 'linear-gradient(135deg, #3b82f6, #1d4ed8)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 2px 8px rgba(37,99,235,0.4)' }}>
              <Shield size={18} color="#fff" />
            </div>
            <div>
              <div style={{ fontSize: '0.95rem', fontWeight: 800, color: '#f8fafc', letterSpacing: '-0.01em', lineHeight: 1.1 }}>
                VeloRoster <span style={{ color: '#3b82f6' }}>Pro</span>
              </div>
              <div style={{ fontSize: '0.625rem', fontWeight: 700, color: '#64748b', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                180×180 Studio
              </div>
            </div>
          </div>

          {/* Company & Seats */}
          {user.company && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 10px', background: 'rgba(255,255,255,0.04)', borderRadius: 'var(--radius-full)', border: '1px solid var(--border-subtle)' }}>
              <Building size={13} color="#94a3b8" />
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#cbd5e1' }}>{user.company.name}</span>
              <span style={{ fontSize: '0.65rem', padding: '1px 6px', borderRadius: 4, background: 'rgba(59,130,246,0.15)', color: '#60a5fa', fontWeight: 700, textTransform: 'uppercase' }}>{user.company.plan}</span>
              <span style={{ fontSize: '0.72rem', color: '#64748b' }}>&bull; {user.company.used_seats}/{user.company.max_seats} Seats</span>
            </div>
          )}

          {/* SuperAdmin Scope Tag */}
          {user.is_superadmin && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '3px 9px', background: 'rgba(168,85,247,0.12)', border: '1px solid rgba(168,85,247,0.3)', borderRadius: 'var(--radius-full)' }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#c084fc', boxShadow: '0 0 6px #c084fc' }} />
              <span style={{ fontSize: '0.72rem', fontWeight: 700, color: '#e9d5ff' }}>SuperAdmin Scope</span>
            </div>
          )}
        </div>

        {/* Right Nav Actions */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {user.is_superadmin && (
            <button
              className="btn-designer btn-designer-secondary"
              style={{ fontSize: '0.75rem', padding: '6px 12px' }}
              onClick={() => setShowPlatformDashboard(true)}
            >
              <Building size={13} />
              <span>Platform Dashboard</span>
            </button>
          )}

          <button
            className="btn-designer btn-designer-secondary"
            style={{ fontSize: '0.75rem', padding: '6px 12px' }}
            onClick={() => setShowTeamModal(true)}
          >
            <Users size={13} />
            <span>Team Seats</span>
          </button>

          <button
            className="btn-designer btn-designer-secondary"
            style={{ fontSize: '0.75rem', padding: '6px 12px', color: '#f87171' }}
            onClick={handleFreeRAM}
            title="Purge RAM and temporary server storage"
          >
            <Cpu size={13} />
            <span>Free RAM</span>
          </button>

          {/* User Profile */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingLeft: 8, borderLeft: '1px solid var(--border-subtle)' }}>
            <div style={{ width: 28, height: 28, borderRadius: '50%', background: '#1e293b', border: '1px solid var(--border-default)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75rem', fontWeight: 700, color: '#93c5fd' }}>
              {user.full_name ? user.full_name.slice(0, 2).toUpperCase() : 'AD'}
            </div>
            <button
              className="btn-designer btn-designer-secondary"
              style={{ padding: '6px 10px' }}
              onClick={handleLogout}
              title="Sign Out"
            >
              <LogOut size={13} />
            </button>
          </div>
        </div>
      </header>

      {/* ========================================================= */}
      {/* SCREEN 1: LANDING WORKFLOW SCREEN */}
      {/* ========================================================= */}
      {currentScreen === 'landing' ? (
        <main style={{ flex: 1, maxWidth: 980, width: '100%', margin: '0 auto', padding: '36px 20px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          {/* Hero Heading */}
          <div style={{ textAlign: 'center', marginBottom: 32 }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 12px', borderRadius: 'var(--radius-full)', background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.2)', marginBottom: 14 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#3b82f6', boxShadow: '0 0 6px #3b82f6' }} />
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#93c5fd' }}>Standardized 180×180 Transparent Headshots &bull; 0 Cloud Storage</span>
            </div>
            <h1 style={{ fontSize: '2rem', fontWeight: 800, color: '#f8fafc', letterSpacing: '-0.02em', lineHeight: 1.2 }}>
              Athletic Roster & <span style={{ color: '#3b82f6' }}>Headshot Studio</span>
            </h1>
            <p style={{ fontSize: '0.875rem', color: '#94a3b8', marginTop: 8, maxWidth: 640 }}>
              Search athletes across global archives, scrape live team rosters, or batch process local photo folders with AI face centering and background removal.
            </p>
          </div>

          {/* 3-Tab Segmented Workflow Switcher */}
          <div style={{ display: 'flex', background: 'rgba(15,23,42,0.7)', padding: 4, borderRadius: 12, border: '1px solid var(--border-default)', marginBottom: 28, width: '100%', maxWidth: 660 }}>
            <button
              className="btn-designer"
              style={{ flex: 1, padding: '9px 0', borderRadius: 8, background: activeWorkflow === 'athlete' ? 'linear-gradient(135deg, #3b82f6, #2563eb)' : 'transparent', color: activeWorkflow === 'athlete' ? '#fff' : '#94a3b8', boxShadow: activeWorkflow === 'athlete' ? '0 2px 8px rgba(37,99,235,0.4)' : 'none' }}
              onClick={() => setActiveWorkflow('athlete')}
            >
              <Search size={14} />
              <span>Single Athlete Search</span>
            </button>
            <button
              className="btn-designer"
              style={{ flex: 1, padding: '9px 0', borderRadius: 8, background: activeWorkflow === 'url' ? 'linear-gradient(135deg, #3b82f6, #2563eb)' : 'transparent', color: activeWorkflow === 'url' ? '#fff' : '#94a3b8', boxShadow: activeWorkflow === 'url' ? '0 2px 8px rgba(37,99,235,0.4)' : 'none' }}
              onClick={() => setActiveWorkflow('url')}
            >
              <Globe size={14} />
              <span>Team Roster Website URL</span>
            </button>
            <button
              className="btn-designer"
              style={{ flex: 1, padding: '9px 0', borderRadius: 8, background: activeWorkflow === 'local' ? 'linear-gradient(135deg, #3b82f6, #2563eb)' : 'transparent', color: activeWorkflow === 'local' ? '#fff' : '#94a3b8', boxShadow: activeWorkflow === 'local' ? '0 2px 8px rgba(37,99,235,0.4)' : 'none' }}
              onClick={() => setActiveWorkflow('local')}
            >
              <Folder size={14} />
              <span>Local Photo Folder</span>
            </button>
          </div>

          {/* WORKFLOW 1: SINGLE ATHLETE SEARCH */}
          {activeWorkflow === 'athlete' && (
            <div className="designer-card" style={{ width: '100%', padding: 28 }}>
              <div style={{ fontSize: '0.8125rem', fontWeight: 700, color: '#3b82f6', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                <Search size={15} />
                <span>Search Athlete with Strict Team & Era Matching</span>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr auto', gap: 14, alignItems: 'end', marginBottom: 20 }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', marginBottom: 6 }}>Player Name (Required)</label>
                  <input
                    type="text"
                    className="designer-input"
                    value={searchPlayerName}
                    onChange={e => setSearchPlayerName(e.target.value)}
                    placeholder="e.g. LeBron James, Wayne Gretzky"
                    onKeyDown={e => e.key === 'Enter' && handleSearchAthlete()}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', marginBottom: 6 }}>Team Name (Strict Filter)</label>
                  <input
                    type="text"
                    className="designer-input"
                    value={searchTeamName}
                    onChange={e => setSearchTeamName(e.target.value)}
                    placeholder="e.g. Miami Heat, Rangers"
                    onKeyDown={e => e.key === 'Enter' && handleSearchAthlete()}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', marginBottom: 6 }}>Destination Folder</label>
                  <input
                    type="text"
                    className="designer-input"
                    value={searchDestinationFolder}
                    onChange={e => setSearchDestinationFolder(e.target.value)}
                    placeholder="Miami Heat - LeBron James"
                    onKeyDown={e => e.key === 'Enter' && handleSearchAthlete()}
                  />
                </div>
                <button
                  className="btn-designer btn-designer-primary"
                  style={{ height: 40 }}
                  onClick={handleSearchAthlete}
                  disabled={searchLoading}
                >
                  <Search size={14} />
                  <span>{searchLoading ? 'Searching...' : 'Search'}</span>
                </button>
              </div>

              {/* Verified Presets */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', paddingTop: 16, borderTop: '1px solid var(--border-subtle)' }}>
                <span style={{ fontSize: '0.72rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Verified Stints:</span>
                {[
                  { name: 'LeBron James', team: 'Miami Heat' },
                  { name: 'Wayne Gretzky', team: 'Rangers' },
                  { name: 'Shaquille O\'Neal', team: 'Lakers' },
                  { name: 'Connor McDavid', team: 'Oilers' },
                  { name: 'Caitlin Clark', team: 'Fever' }
                ].map((preset, idx) => (
                  <button
                    key={idx}
                    type="button"
                    className="btn-designer btn-designer-secondary"
                    style={{ fontSize: '0.72rem', padding: '4px 10px' }}
                    onClick={() => {
                      setSearchPlayerName(preset.name);
                      setSearchTeamName(preset.team);
                      setSearchDestinationFolder(`${preset.team} - ${preset.name}`);
                    }}
                  >
                    {preset.name} ({preset.team})
                  </button>
                ))}
              </div>

              {/* Player Options Results */}
              {searchPlayerOptions.length > 0 && (
                <div style={{ marginTop: 24, paddingTop: 20, borderTop: '1px solid var(--border-default)' }}>
                  <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#f8fafc', marginBottom: 12 }}>
                    Found {searchPlayerOptions.length} Verified Stints & High-Res Portraits:
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 12, marginBottom: 20 }}>
                    {searchPlayerOptions.map((opt, idx) => (
                      <div
                        key={idx}
                        onClick={() => setSelectedPhotoOptionIdx(idx)}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 12,
                          padding: 10,
                          borderRadius: 'var(--radius-md)',
                          background: selectedPhotoOptionIdx === idx ? 'rgba(59,130,246,0.15)' : 'rgba(15,23,42,0.6)',
                          border: `1.5px solid ${selectedPhotoOptionIdx === idx ? '#3b82f6' : 'var(--border-subtle)'}`,
                          cursor: 'pointer',
                          transition: 'all 0.15s ease'
                        }}
                      >
                        <img
                          src={opt.image ? `/api/proxy_photo?url=${encodeURIComponent(opt.image)}&width=200` : ''}
                          alt={opt.team}
                          style={{ width: 54, height: 54, borderRadius: 8, objectFit: 'cover', background: '#0f172a' }}
                          onError={(e) => { (e.target as HTMLElement).style.opacity = '0.2'; }}
                        />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: '0.8125rem', fontWeight: 700, color: '#f8fafc', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {opt.team}
                          </div>
                          <div style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
                            {opt.years || 'Era active'} {opt.jersey ? `&bull; #${opt.jersey}` : ''}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
                    <button
                      className="btn-designer btn-designer-primary"
                      style={{ padding: '10px 24px', fontSize: '0.875rem' }}
                      onClick={loadSingleAthleteIntoStudio}
                    >
                      <Sparkles size={16} />
                      <span>Open in Studio Workbench</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* WORKFLOW 2: TEAM ROSTER WEBSITE URL */}
          {activeWorkflow === 'url' && (
            <div className="designer-card" style={{ width: '100%', padding: 28 }}>
              <div style={{ fontSize: '0.8125rem', fontWeight: 700, color: '#3b82f6', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                <Globe size={15} />
                <span>Full League Team Roster Ingestion (Proballers, Eurobasket, NHL, EIHL, NCAA)</span>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 240px auto', gap: 14, alignItems: 'end', marginBottom: 20 }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', marginBottom: 6 }}>Team Roster Website URL</label>
                  <input
                    type="text"
                    className="designer-input"
                    value={rosterUrl}
                    onChange={e => setRosterUrl(e.target.value)}
                    placeholder="https://www.cardiffdevils.com/team/ or Proballers URL"
                    onKeyDown={e => e.key === 'Enter' && handleFetchTeamRoster()}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', marginBottom: 6 }}>Destination Folder</label>
                  <input
                    type="text"
                    className="designer-input"
                    value={rosterFolder}
                    onChange={e => setRosterFolder(e.target.value)}
                    placeholder="Cardiff Devils"
                    onKeyDown={e => e.key === 'Enter' && handleFetchTeamRoster()}
                  />
                </div>
                <button
                  className="btn-designer btn-designer-primary"
                  style={{ height: 40 }}
                  onClick={handleFetchTeamRoster}
                  disabled={rosterLoading}
                >
                  <Globe size={14} />
                  <span>{rosterLoading ? 'Scraping...' : 'Fetch Roster'}</span>
                </button>
              </div>

              {/* Quick Presets */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', paddingTop: 16, borderTop: '1px solid var(--border-subtle)' }}>
                <span style={{ fontSize: '0.72rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Supported Presets:</span>
                {[
                  { name: 'Cardiff Devils (EIHL)', url: 'https://www.cardiffdevils.com/team/', folder: 'Cardiff Devils' },
                  { name: 'Buffalo Sabres (NHL)', url: 'https://www.nhl.com/sabres/roster', folder: 'Buffalo Sabres' },
                  { name: 'Caen U21 (Proballers)', url: 'https://www.proballers.com/basketball/team/15352/caen-u21/roster', folder: 'Caen U21' },
                  { name: 'Debreceni Egyetem (Eurobasket)', url: 'https://basketball.eurobasket.com/team/Debreceni-Egyetem/1833/Roster/2026-2027#google_vignette', folder: 'Debreceni Egyetem' }
                ].map((preset, idx) => (
                  <button
                    key={idx}
                    type="button"
                    className="btn-designer btn-designer-secondary"
                    style={{ fontSize: '0.72rem', padding: '4px 10px' }}
                    onClick={() => {
                      setRosterUrl(preset.url);
                      setRosterFolder(preset.folder);
                    }}
                  >
                    {preset.name}
                  </button>
                ))}
              </div>

              {/* Roster Table Results */}
              {rosterPlayers.length > 0 && (
                <div style={{ marginTop: 24, paddingTop: 20, borderTop: '1px solid var(--border-default)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span style={{ fontSize: '0.95rem', fontWeight: 800, color: '#f8fafc' }}>{rosterFolder}</span>
                      <span style={{ fontSize: '0.72rem', padding: '2px 8px', borderRadius: 'var(--radius-full)', background: 'rgba(59,130,246,0.15)', color: '#60a5fa', fontWeight: 700 }}>
                        {rosterPlayers.length} Players
                      </span>
                    </div>

                    <div style={{ display: 'flex', gap: 8 }}>
                      <button
                        className="btn-designer btn-designer-secondary"
                        style={{ fontSize: '0.75rem', padding: '5px 10px' }}
                        onClick={handleCopyForSheets}
                      >
                        <Copy size={13} />
                        <span>Copy for Sheets</span>
                      </button>
                      <button
                        className="btn-designer btn-designer-secondary"
                        style={{ fontSize: '0.75rem', padding: '5px 10px' }}
                        onClick={() => setBulkPasteOpen(!bulkPasteOpen)}
                      >
                        <FileSpreadsheet size={13} />
                        <span>Bulk Paste IDs</span>
                      </button>
                    </div>
                  </div>

                  {/* Bulk Paste Drawer */}
                  {bulkPasteOpen && (
                    <div style={{ background: 'rgba(15,23,42,0.8)', padding: 14, borderRadius: 10, border: '1px solid var(--border-default)', marginBottom: 14 }}>
                      <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', marginBottom: 6 }}>
                        Paste Name &lt;Tab&gt; Number from Google Sheets or Excel:
                      </div>
                      <textarea
                        rows={3}
                        className="designer-input"
                        placeholder="Marcus Meeks&#9;882177&#10;Braeden Elnicki&#9;1947454..."
                        value={bulkPasteText}
                        onChange={e => setBulkPasteText(e.target.value)}
                        style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}
                      />
                      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 8 }}>
                        <button className="btn-designer btn-designer-secondary" style={{ fontSize: '0.72rem' }} onClick={() => setBulkPasteOpen(false)}>Cancel</button>
                        <button className="btn-designer btn-designer-primary" style={{ fontSize: '0.72rem' }} onClick={handleApplyBulkPaste}>Apply to Table</button>
                      </div>
                    </div>
                  )}

                  {/* Table */}
                  <div style={{ maxHeight: 360, overflowY: 'auto', border: '1px solid var(--border-subtle)', borderRadius: 10, marginBottom: 20 }}>
                    <table className="designer-table">
                      <thead>
                        <tr>
                          <th style={{ width: 60 }}>Avatar</th>
                          <th>Athlete Name</th>
                          <th style={{ width: 60, textAlign: 'center' }}>#</th>
                          <th style={{ width: 80, textAlign: 'center' }}>Pos</th>
                          <th style={{ width: 140 }}>Assigned ID</th>
                          <th style={{ width: 140 }}>Resulting File</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rosterPlayers.map((player, idx) => (
                          <tr key={idx}>
                            <td>
                              <img
                                src={player.image ? `/api/proxy_photo?url=${encodeURIComponent(player.image)}&width=100` : ''}
                                alt={player.name}
                                style={{ width: 34, height: 34, borderRadius: 6, objectFit: 'cover', background: '#0f172a' }}
                                onError={(e) => { (e.target as HTMLElement).style.opacity = '0.2'; }}
                              />
                            </td>
                            <td style={{ fontWeight: 600, color: '#f8fafc' }}>{player.name}</td>
                            <td style={{ textAlign: 'center', color: '#94a3b8' }}>{player.jersey || '-'}</td>
                            <td style={{ textAlign: 'center', color: '#94a3b8' }}>{player.position || player.pos || '-'}</td>
                            <td>
                              <input
                                type="text"
                                className="designer-input"
                                style={{ padding: '4px 8px', fontSize: '0.75rem', height: 28 }}
                                value={player.assigned_number || ''}
                                placeholder={player.jersey || `${idx + 1}`}
                                onChange={e => {
                                  const val = e.target.value;
                                  const updated = [...rosterPlayers];
                                  updated[idx] = { ...updated[idx], assigned_number: val };
                                  setRosterPlayers(updated);
                                }}
                              />
                            </td>
                            <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: '#38bdf8' }}>
                              {player.assigned_number ? `${player.assigned_number}.png` : (player.jersey ? `${player.jersey}.png` : `${player.name}.png`)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
                    <button
                      className="btn-designer btn-designer-primary"
                      style={{ padding: '10px 24px', fontSize: '0.875rem' }}
                      onClick={loadTeamRosterIntoStudio}
                    >
                      <Sparkles size={16} />
                      <span>Open in Studio Workbench ({rosterPlayers.length} Athletes)</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* WORKFLOW 3: LOCAL PHOTO FOLDER */}
          {activeWorkflow === 'local' && (
            <div className="designer-card" style={{ width: '100%', padding: 28 }}>
              {/* Dropzone Card */}
              <div
                style={{
                  border: '2px dashed var(--border-default)',
                  borderRadius: 'var(--radius-lg)',
                  padding: '40px 24px',
                  textAlign: 'center',
                  background: 'rgba(15,23,42,0.4)',
                  marginBottom: 24,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: 12
                }}
              >
                <div style={{ width: 52, height: 52, borderRadius: 14, background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.25)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#3b82f6' }}>
                  <Folder size={26} />
                </div>
                <div style={{ fontSize: '1rem', fontWeight: 700, color: '#f8fafc' }}>
                  Choose Photo Folder or Drag & Drop Images Here
                </div>
                <div style={{ fontSize: '0.8125rem', color: '#94a3b8' }}>
                  Select an entire folder from your computer with native webkit folder picker
                </div>
                <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
                  <label className="btn-designer btn-designer-primary" style={{ cursor: 'pointer' }}>
                    <Folder size={15} />
                    <span>Choose Photo Folder</span>
                    <input
                      type="file"
                      // @ts-expect-error webkitdirectory is standard for Chromium/Safari folder picker
                      webkitdirectory=""
                      directory=""
                      multiple
                      style={{ display: 'none' }}
                      onChange={handleNativeFolderPicked}
                    />
                  </label>
                </div>
              </div>

              {/* Manual Path Bar */}
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 28 }}>
                <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', whiteSpace: 'nowrap' }}>Or enter folder path:</span>
                <input
                  type="text"
                  className="designer-input"
                  placeholder="/Users/.../Downloads/Team_Photos or 1908-Saint Anselm"
                  value={manualPath}
                  onChange={e => setManualPath(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleOpenLocalFolder(manualPath)}
                />
                <button
                  className="btn-designer btn-designer-secondary"
                  onClick={() => handleOpenLocalFolder(manualPath)}
                  disabled={folderLoading}
                >
                  Open
                </button>
              </div>

              {/* Detected Folders in Downloads */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                  <div style={{ fontSize: '0.8125rem', fontWeight: 700, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <HardDrive size={15} color="#3b82f6" />
                    <span>Detected Photo Folders in Downloads</span>
                    <span style={{ fontSize: '0.6875rem', padding: '1px 6px', borderRadius: 4, background: 'rgba(59,130,246,0.15)', color: '#60a5fa', fontWeight: 700 }}>
                      {detectedFolders.length}
                    </span>
                  </div>
                  <button
                    className="btn-designer btn-designer-secondary"
                    style={{ fontSize: '0.72rem', padding: '3px 8px' }}
                    onClick={loadSuggestedFolders}
                  >
                    <RefreshCw size={11} />
                    <span>Refresh</span>
                  </button>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 10 }}>
                  {detectedFolders.length > 0 ? (
                    detectedFolders.map((f, idx) => (
                      <div
                        key={idx}
                        onClick={() => handleOpenLocalFolder(f.path)}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 12,
                          padding: '12px 14px',
                          borderRadius: 10,
                          background: 'rgba(15,23,42,0.6)',
                          border: '1px solid var(--border-subtle)',
                          cursor: 'pointer',
                          transition: 'all 0.15s ease'
                        }}
                      >
                        <Folder size={18} color="#3b82f6" />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: '0.8125rem', fontWeight: 700, color: '#f8fafc', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {f.name}
                          </div>
                          <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>
                            {f.count} {f.count === 1 ? 'photo' : 'photos'} &bull; Ready to edit
                          </div>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div style={{ gridColumn: '1 / -1', padding: 20, textAlign: 'center', color: '#64748b', fontSize: '0.8125rem' }}>
                      No photo folders found automatically in Downloads. Use Choose Photo Folder above.
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </main>
      ) : (
        /* ========================================================= */
        /* SCREEN 2: STUDIO WORKBENCH SCREEN */
        /* ========================================================= */
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: 'calc(100vh - 60px)', overflow: 'hidden' }}>
          {/* Workbench Action Header */}
          <div style={{ height: 52, borderBottom: '1px solid var(--border-subtle)', background: 'rgba(13,19,31,0.95)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 20px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              <button
                className="btn-designer btn-designer-secondary"
                style={{ fontSize: '0.75rem', padding: '5px 10px' }}
                onClick={() => setCurrentScreen('landing')}
              >
                <ArrowLeft size={13} />
                <span>Change Folder</span>
              </button>

              <div style={{ display: 'flex', flexDirection: 'column' }}>
                <span style={{ fontSize: '0.8125rem', fontWeight: 700, color: '#f8fafc' }}>
                  {currentFolder.replaceAll('\\', '/').split('/').filter(Boolean).pop() || currentFolder}
                </span>
                <span style={{ fontSize: '0.6875rem', fontFamily: 'var(--font-mono)', color: '#38bdf8' }}>
                  &rarr; {editedFolder.replaceAll('\\', '/').split('/').filter(Boolean).pop() || editedFolder}/
                </span>
              </div>
            </div>

            {/* Header Actions */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button
                className="btn-designer btn-designer-secondary"
                style={{ fontSize: '0.75rem' }}
                onClick={handleCutout}
                title="Automated background removal with u2net"
              >
                <Scissors size={14} color="#a855f7" />
                <span>AI Cutout</span>
              </button>

              <button
                className="btn-designer btn-designer-secondary"
                style={{ fontSize: '0.75rem' }}
                onClick={handleSaveActivePhoto}
                title="Save 180×180 PNG directly"
              >
                <Save size={14} color="#10b981" />
                <span>Save Headshot</span>
              </button>

              <button
                className="btn-designer btn-designer-primary"
                style={{ fontSize: '0.75rem' }}
                onClick={handleDownloadAllZip}
                title="Export all photos as 180×180 ZIP package"
              >
                <Download size={14} />
                <span>Download All (ZIP)</span>
              </button>
            </div>
          </div>

          {/* Workbench Body */}
          <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
            {/* Left Controls Sidebar */}
            <div style={{ width: 280, borderRight: '1px solid var(--border-subtle)', background: 'rgba(13,19,31,0.6)', padding: 18, display: 'flex', flexDirection: 'column', gap: 20, overflowY: 'auto' }}>
              {/* Tool Mode Tabs */}
              <div>
                <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
                  Tool Mode
                </div>
                <div style={{ display: 'flex', background: 'rgba(15,23,42,0.8)', padding: 3, borderRadius: 8, border: '1px solid var(--border-subtle)' }}>
                  <button
                    className="btn-designer"
                    style={{ flex: 1, padding: '6px 0', fontSize: '0.75rem', borderRadius: 6, background: toolMode === 'frame' ? 'rgba(59,130,246,0.2)' : 'transparent', color: toolMode === 'frame' ? '#60a5fa' : '#94a3b8' }}
                    onClick={() => setToolMode('frame')}
                  >
                    <Move size={13} />
                    <span>Pan</span>
                  </button>
                  <button
                    className="btn-designer"
                    style={{ flex: 1, padding: '6px 0', fontSize: '0.75rem', borderRadius: 6, background: toolMode === 'recover' ? 'rgba(16,185,129,0.2)' : 'transparent', color: toolMode === 'recover' ? '#34d399' : '#94a3b8' }}
                    onClick={() => setToolMode('recover')}
                  >
                    <Sparkles size={13} />
                    <span>Recover</span>
                  </button>
                  <button
                    className="btn-designer"
                    style={{ flex: 1, padding: '6px 0', fontSize: '0.75rem', borderRadius: 6, background: toolMode === 'erase' ? 'rgba(239,68,68,0.2)' : 'transparent', color: toolMode === 'erase' ? '#f87171' : '#94a3b8' }}
                    onClick={() => setToolMode('erase')}
                  >
                    <Eraser size={13} />
                    <span>Erase</span>
                  </button>
                </div>
              </div>

              {/* Mode 1: Pan & Zoom Controls */}
              {toolMode === 'frame' ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <div className="designer-card" style={{ padding: 14 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                      <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8' }}>Zoom Scale</span>
                      <span style={{ fontSize: '0.72rem', fontFamily: 'var(--font-mono)', color: '#38bdf8' }}>
                        {photoDataMap[photos[currentIndex]] ? Math.round(photoDataMap[photos[currentIndex]].scale * 100) : 45}%
                      </span>
                    </div>
                    <input
                      type="range"
                      min="10"
                      max="150"
                      value={photoDataMap[photos[currentIndex]] ? Math.round(photoDataMap[photos[currentIndex]].scale * 100) : 45}
                      onChange={e => {
                        const val = parseInt(e.target.value) / 100;
                        const pName = photos[currentIndex];
                        const data = photoDataMap[pName];
                        if (data) {
                          data.scale = val;
                          setPhotoDataMap(prev => ({ ...prev, [pName]: { ...data } }));
                        }
                      }}
                      style={{ width: '100%', accentColor: '#3b82f6', marginBottom: 12 }}
                    />
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                      <button className="btn-designer btn-designer-secondary" style={{ fontSize: '0.72rem', padding: '6px 0' }} onClick={handleAutoAlignCurrent}>Auto-Align Face</button>
                      <button className="btn-designer btn-designer-secondary" style={{ fontSize: '0.72rem', padding: '6px 0' }} onClick={handleFitWidth}>Fit Width</button>
                      <button className="btn-designer btn-designer-secondary" style={{ fontSize: '0.72rem', padding: '6px 0' }} onClick={handleFitHeight}>Fit Height</button>
                      <button className="btn-designer btn-designer-secondary" style={{ fontSize: '0.72rem', padding: '6px 0' }} onClick={handleCenter}>Center</button>
                    </div>
                  </div>

                  <div className="designer-card" style={{ padding: 14 }}>
                    <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#f8fafc', marginBottom: 4 }}>
                      Batch Team Framing
                    </div>
                    <p style={{ fontSize: '0.7rem', color: '#94a3b8', lineHeight: 1.4, marginBottom: 10 }}>
                      Apply this photo&apos;s scale & position to all {photos.length} portraits in roster:
                    </p>
                    <button
                      className="btn-designer btn-designer-secondary"
                      style={{ width: '100%', fontSize: '0.75rem' }}
                      onClick={handleApplyFramingToAll}
                    >
                      <Layers size={13} />
                      <span>Apply Framing to All</span>
                    </button>
                  </div>
                </div>
              ) : (
                /* Mode 2 & 3: Retouch Brush Controls */
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <div className="designer-card" style={{ padding: 14 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                      <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8' }}>Brush Radius</span>
                      <span style={{ fontSize: '0.72rem', fontFamily: 'var(--font-mono)', color: '#38bdf8' }}>{brushSize} px</span>
                    </div>
                    <input
                      type="range"
                      min="4"
                      max="70"
                      value={brushSize}
                      onChange={e => setBrushSize(parseInt(e.target.value))}
                      style={{ width: '100%', accentColor: toolMode === 'recover' ? '#10b981' : '#ef4444', marginBottom: 12 }}
                    />
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button className="btn-designer btn-designer-secondary" style={{ flex: 1, fontSize: '0.72rem' }} onClick={handleUndoMask}>Undo</button>
                      <button className="btn-designer btn-designer-secondary" style={{ flex: 1, fontSize: '0.72rem' }} onClick={handleResetMask}>Reset Cutout</button>
                    </div>
                    <p style={{ fontSize: '0.7rem', color: '#64748b', marginTop: 10, lineHeight: 1.4 }}>
                      {toolMode === 'recover'
                        ? 'Painting recovers lost hair strands and jersey details from original photo.'
                        : 'Painting erases leftover background artifacts.'}
                    </p>
                  </div>
                </div>
              )}

              {/* Standardized Specs Card */}
              <div className="designer-card" style={{ padding: 14, marginTop: 'auto' }}>
                <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', marginBottom: 6 }}>
                  Target Calibration
                </div>
                <div style={{ fontSize: '0.72rem', color: '#94a3b8', lineHeight: 1.6, fontFamily: 'var(--font-mono)' }}>
                  <div>Target: <strong style={{ color: '#38bdf8' }}>180 × 180 px</strong></div>
                  <div>Guideline: <strong style={{ color: '#7dd3fc' }}>35% Eye Line</strong></div>
                  <div>Guideline: <strong style={{ color: '#fcd34d' }}>85% Chin Line</strong></div>
                  <div>Format: <strong style={{ color: '#34d399' }}>PNG (RGBA)</strong></div>
                </div>
              </div>
            </div>

            {/* Center Stage & HUD Canvas */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', position: 'relative', overflow: 'hidden' }}>
              {/* Background Color Toolbar */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 14 }}>
                <button
                  className="btn-designer btn-designer-secondary"
                  style={{ fontSize: '0.72rem', padding: '4px 10px', background: canvasBg === 'checker' ? 'rgba(59,130,246,0.2)' : 'transparent', color: canvasBg === 'checker' ? '#60a5fa' : '#94a3b8' }}
                  onClick={() => setCanvasBg('checker')}
                >
                  Transparent
                </button>
                <button
                  className="btn-designer btn-designer-secondary"
                  style={{ fontSize: '0.72rem', padding: '4px 10px', background: canvasBg === 'dark' ? 'rgba(59,130,246,0.2)' : 'transparent', color: canvasBg === 'dark' ? '#60a5fa' : '#94a3b8' }}
                  onClick={() => setCanvasBg('dark')}
                >
                  Dark
                </button>
                <button
                  className="btn-designer btn-designer-secondary"
                  style={{ fontSize: '0.72rem', padding: '4px 10px', background: canvasBg === 'white' ? 'rgba(59,130,246,0.2)' : 'transparent', color: canvasBg === 'white' ? '#60a5fa' : '#94a3b8' }}
                  onClick={() => setCanvasBg('white')}
                >
                  White
                </button>
                <button
                  className="btn-designer btn-designer-secondary"
                  style={{ fontSize: '0.72rem', padding: '4px 10px', background: canvasBg === 'team' ? 'rgba(59,130,246,0.2)' : 'transparent', color: canvasBg === 'team' ? '#60a5fa' : '#94a3b8' }}
                  onClick={() => setCanvasBg('team')}
                >
                  Team Navy
                </button>
                <span style={{ width: 1, height: 16, background: 'var(--border-subtle)', margin: '0 4px' }} />
                <button
                  className="btn-designer btn-designer-secondary"
                  style={{ fontSize: '0.72rem', padding: '4px 10px', background: isComparingOriginal ? '#3b82f6' : 'transparent', color: isComparingOriginal ? '#fff' : '#94a3b8' }}
                  onMouseDown={() => setIsComparingOriginal(true)}
                  onMouseUp={() => setIsComparingOriginal(false)}
                  onMouseLeave={() => setIsComparingOriginal(false)}
                >
                  <Eye size={12} />
                  <span>Hold: View Original</span>
                </button>
              </div>

              {/* Viewport Canvas Frame */}
              <div className="hud-viewport-wrapper">
                <div
                  ref={viewportRef}
                  className={`hud-viewport bg-${canvasBg} ${toolMode !== 'frame' ? 'brush-mode' : ''}`}
                  onMouseDown={handleCanvasMouseDown}
                  onMouseMove={handleCanvasMouseMove}
                  onMouseUp={handleCanvasMouseUp}
                  onWheel={handleCanvasWheel}
                >
                  <canvas
                    ref={canvasRef}
                    width={BUFFER_PX}
                    height={BUFFER_PX}
                    style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
                  />

                  {/* HUD Guidelines */}
                  <div className="hud-guidelines-overlay">
                    <div className="hud-guide-eye">
                      <span>35% Eye Line</span>
                    </div>
                    <div className="hud-guide-chin">
                      <span>85% Chin Line</span>
                    </div>
                    <div className="hud-crosshair-v" />
                    <div className="hud-crosshair-h" />
                  </div>

                  {/* Brush Indicator */}
                  <div
                    ref={brushCursorRef}
                    className={`brush-cursor-indicator ${toolMode}`}
                  />
                </div>
              </div>

              {/* Coordinates Hint */}
              <div style={{ marginTop: 12, fontSize: '0.72rem', color: '#64748b', display: 'flex', alignItems: 'center', gap: 8 }}>
                <span>Drag to reposition &bull; Wheel to zoom</span>
                <span>&bull;</span>
                <span style={{ fontFamily: 'var(--font-mono)', color: '#38bdf8' }}>
                  {photos[currentIndex] && photoDataMap[photos[currentIndex]]
                    ? `x: ${Math.round(photoDataMap[photos[currentIndex]].offset_x)}px, y: ${Math.round(photoDataMap[photos[currentIndex]].offset_y)}px`
                    : 'x: 0px, y: 0px'}
                </span>
              </div>
            </div>
          </div>

          {/* Bottom Filmstrip Carousel */}
          <div style={{ height: 130, borderTop: '1px solid var(--border-subtle)', background: 'rgba(13,19,31,0.95)', padding: '8px 16px', display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                  Team Roster Filmstrip
                </span>
                <span style={{ fontSize: '0.65rem', padding: '1px 6px', borderRadius: 4, background: 'rgba(59,130,246,0.12)', color: '#60a5fa', fontWeight: 600 }}>
                  Photo {currentIndex + 1} of {photos.length}
                </span>
              </div>

              <div style={{ display: 'flex', gap: 4 }}>
                <button
                  className="btn-designer btn-designer-secondary"
                  style={{ padding: '3px 7px' }}
                  onClick={() => selectPhotoByIndex((currentIndex - 1 + photos.length) % photos.length)}
                  title="Previous Photo (Left Arrow)"
                >
                  <ArrowLeft size={12} />
                </button>
                <button
                  className="btn-designer btn-designer-secondary"
                  style={{ padding: '3px 7px' }}
                  onClick={() => selectPhotoByIndex((currentIndex + 1) % photos.length)}
                  title="Next Photo (Right Arrow)"
                >
                  <ArrowRight size={12} />
                </button>
              </div>
            </div>

            <div className="filmstrip-container">
              {photos.map((name, idx) => {
                const data = photoDataMap[name];
                return (
                  <div
                    key={idx}
                    className={`filmstrip-card ${idx === currentIndex ? 'active' : ''}`}
                    onClick={() => selectPhotoByIndex(idx)}
                  >
                    {data?.saved && <div className="status-dot-badge dot-saved" title="Saved" />}
                    {data?.hasCutout && !data?.saved && <div className="status-dot-badge dot-cutout" title="AI Cutout" />}
                    <img
                      src={data?.proxiedUrl || data?.blobUrl || `/api/proxy_photo?url=${encodeURIComponent(name)}&width=100`}
                      alt={name}
                      onError={(e) => { (e.target as HTMLElement).style.opacity = '0.2'; }}
                    />
                    <span title={name}>{name}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* MODAL: Platform Dashboard (SuperAdmin) */}
      {/* ========================================================= */}
      {showPlatformDashboard && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(8,12,20,0.8)', backdropFilter: 'blur(8px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
          <div className="designer-card" style={{ maxWidth: 640, width: '100%', padding: 28, maxHeight: '85vh', overflowY: 'auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <Building size={20} color="#3b82f6" />
                <h2 style={{ fontSize: '1.15rem', fontWeight: 800, color: '#f8fafc' }}>Multi-Tenant Platform Dashboard</h2>
              </div>
              <button className="btn-designer btn-designer-secondary" style={{ padding: '4px 10px' }} onClick={() => setShowPlatformDashboard(false)}>Close</button>
            </div>

            {/* Metrics Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 20 }}>
              <div style={{ padding: 12, borderRadius: 10, background: 'rgba(15,23,42,0.6)', border: '1px solid var(--border-subtle)' }}>
                <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Active Companies</div>
                <div style={{ fontSize: '1.4rem', fontWeight: 800, color: '#f8fafc', marginTop: 4 }}>
                  {user.platform_metrics?.total_companies || 1}
                </div>
              </div>
              <div style={{ padding: 12, borderRadius: 10, background: 'rgba(15,23,42,0.6)', border: '1px solid var(--border-subtle)' }}>
                <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Seats Allocated</div>
                <div style={{ fontSize: '1.4rem', fontWeight: 800, color: '#38bdf8', marginTop: 4 }}>
                  {user.platform_metrics?.total_used_seats || 1} / {user.platform_metrics?.total_seats_allocated || 25}
                </div>
              </div>
              <div style={{ padding: 12, borderRadius: 10, background: 'rgba(15,23,42,0.6)', border: '1px solid var(--border-subtle)' }}>
                <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Total Users</div>
                <div style={{ fontSize: '1.4rem', fontWeight: 800, color: '#34d399', marginTop: 4 }}>
                  {user.platform_metrics?.total_users || 2}
                </div>
              </div>
            </div>

            {/* Companies List */}
            <div style={{ fontSize: '0.8125rem', fontWeight: 700, color: '#f8fafc', marginBottom: 10 }}>Registered Tenants</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {(user.platform_metrics?.companies || [
                { id: '1', name: 'Athletics Media Group', plan: 'enterprise', max_seats: 25, used_seats: 1, status: 'active' }
              ]).map((c, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: 12, borderRadius: 8, background: 'rgba(15,23,42,0.4)', border: '1px solid var(--border-subtle)' }}>
                  <div>
                    <div style={{ fontSize: '0.875rem', fontWeight: 700, color: '#f8fafc' }}>{c.name}</div>
                    <div style={{ fontSize: '0.72rem', color: '#64748b' }}>Plan: {c.plan} &bull; Status: {c.status}</div>
                  </div>
                  <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#93c5fd' }}>
                    {c.used_seats} / {c.max_seats} Seats Used
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* MODAL: Team Seats & Member Invitations */}
      {/* ========================================================= */}
      {showTeamModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(8,12,20,0.8)', backdropFilter: 'blur(8px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
          <div className="designer-card" style={{ maxWidth: 480, width: '100%', padding: 28 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <Users size={18} color="#3b82f6" />
                <h2 style={{ fontSize: '1.1rem', fontWeight: 800, color: '#f8fafc' }}>Team Seats & Invitations</h2>
              </div>
              <button className="btn-designer btn-designer-secondary" style={{ padding: '4px 10px' }} onClick={() => setShowTeamModal(false)}>Close</button>
            </div>

            <div style={{ padding: 12, borderRadius: 8, background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.2)', marginBottom: 18 }}>
              <div style={{ fontSize: '0.75rem', color: '#93c5fd' }}>
                Remaining Quota: <strong>{user.company ? user.company.remaining_seats : 24} available seats</strong>
              </div>
            </div>

            <form
              onSubmit={async e => {
                e.preventDefault();
                try {
                  const res = await fetch('/api/company/users/invite', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: inviteEmail, full_name: inviteName, role: inviteRole })
                  });
                  const data = await res.json();
                  if (res.ok && data.status === 'ok') {
                    setInviteLink(window.location.origin + data.activation_url);
                    showToast('Invitation generated!');
                  } else {
                    showToast(data.message || 'Invitation failed');
                  }
                } catch {
                  showToast('Error sending invitation');
                }
              }}
              style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
            >
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', marginBottom: 4 }}>Colleague Email</label>
                <input
                  type="email"
                  className="designer-input"
                  placeholder="editor@athletics.com"
                  value={inviteEmail}
                  onChange={e => setInviteEmail(e.target.value)}
                  required
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', marginBottom: 4 }}>Full Name</label>
                <input
                  type="text"
                  className="designer-input"
                  placeholder="Taylor Swift"
                  value={inviteName}
                  onChange={e => setInviteName(e.target.value)}
                  required
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', marginBottom: 4 }}>Role</label>
                <select
                  className="designer-input"
                  value={inviteRole}
                  onChange={e => setInviteRole(e.target.value as 'member' | 'company_admin')}
                >
                  <option value="member">Standard Member</option>
                  <option value="company_admin">Team Administrator</option>
                </select>
              </div>

              <button type="submit" className="btn-designer btn-designer-primary" style={{ padding: '10px 0', marginTop: 4 }}>
                Generate Seat Invite Token
              </button>
            </form>

            {inviteLink && (
              <div style={{ marginTop: 16, padding: 12, borderRadius: 8, background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.3)' }}>
                <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#34d399', marginBottom: 4 }}>Activation Link:</div>
                <div style={{ fontSize: '0.72rem', fontFamily: 'var(--font-mono)', color: '#a7f3d0', wordBreak: 'break-all' }}>
                  {inviteLink}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
