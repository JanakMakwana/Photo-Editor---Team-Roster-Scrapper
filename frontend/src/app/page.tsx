'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Shield, Users, Building, LogOut, Search, Globe, Folder,
  Scissors, Save, Download, Sparkles, Move, Eraser,
  RefreshCw, ArrowLeft, ArrowRight, Copy, FileSpreadsheet,
  Layers, Eye, AlertCircle, HardDrive, Cpu, Check, ExternalLink,
  ChevronRight, Sliders, Crosshair, Plus, Trash2, Edit2, Zap,
  Settings, Activity, UserPlus, Server
} from 'lucide-react';
import JSZip from 'jszip';

interface User {
  id: string;
  email: string;
  full_name: string;
  role: 'superadmin' | 'company_admin' | 'member' | 'viewer';
  is_superadmin: boolean;
  is_company_admin: boolean;
  can_manage_team: boolean;
  permissions: string[];
  mfa_enabled: boolean;
  company: {
    id: string;
    name: string;
    slug: string;
    plan: string;
    max_seats: number;
    used_seats: number;
    pending_invitations?: number;
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

interface OrgMember {
  id: string;
  email: string;
  full_name: string;
  role: 'superadmin' | 'company_admin' | 'member' | 'viewer';
  is_superadmin: boolean;
  is_self: boolean;
  date_joined: string;
}

interface OrgInvitation {
  id: string;
  email: string;
  full_name: string;
  role: string;
  token: string;
  activation_url: string;
  is_expired: boolean;
  created_at: string;
  expires_at: string | null;
  invited_by: string | null;
}

interface InvitationDetails {
  valid: boolean;
  email: string;
  full_name: string;
  role: string;
  company_name: string;
  company_plan: string;
  is_expired: boolean;
  is_accepted: boolean;
  is_revoked: boolean;
  expires_at: string | null;
}

interface PlanItem {
  id: string;
  name: string;
  slug: string;
  default_max_seats: number;
  price_monthly: string;
  description: string;
  is_active: boolean;
  created_at: string;
}

interface CompanyItem {
  id: string;
  name: string;
  slug: string;
  plan: string;
  max_seats: number;
  used_seats: number;
  status: string;
  created_at: string;
}

interface PlatformUser {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_superadmin: boolean;
  company_id: string | null;
  company_name: string;
  is_active: boolean;
  date_joined: string;
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

  // Modals & Navigation
  const [showPlatformDashboard, setShowPlatformDashboard] = useState(false);
  const [showOrgHub, setShowOrgHub] = useState(false);
  const [orgHubTab, setOrgHubTab] = useState<'members' | 'invitations' | 'invite'>('members');
  const [orgMembers, setOrgMembers] = useState<OrgMember[]>([]);
  const [orgInvitations, setOrgInvitations] = useState<OrgInvitation[]>([]);
  const [orgDataLoading, setOrgDataLoading] = useState(false);
  const [orgActionLoading, setOrgActionLoading] = useState(false);
  const [orgMemberSearch, setOrgMemberSearch] = useState('');
  const [showRoleSwitcher, setShowRoleSwitcher] = useState(false);

  // Dedicated Activation Modal State
  const [showActivationModal, setShowActivationModal] = useState(false);
  const [activationToken, setActivationToken] = useState('');
  const [activationDetails, setActivationDetails] = useState<InvitationDetails | null>(null);
  const [activationPassword, setActivationPassword] = useState('');
  const [activationConfirmPassword, setActivationConfirmPassword] = useState('');
  const [activationFullName, setActivationFullName] = useState('');
  const [activationLoading, setActivationLoading] = useState(false);
  const [activationError, setActivationError] = useState('');

  // Legacy / Direct Invite State
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteName, setInviteName] = useState('');
  const [inviteRole, setInviteRole] = useState<'member' | 'company_admin'>('member');
  const [inviteLink, setInviteLink] = useState('');

  // SuperAdmin Organization Hub Tabs & State
  const [superAdminTab, setSuperAdminTab] = useState<'companies' | 'create_comp' | 'plans' | 'members' | 'keepalive'>('companies');
  const [adminCompaniesList, setAdminCompaniesList] = useState<CompanyItem[]>([]);
  const [adminPlansList, setAdminPlansList] = useState<PlanItem[]>([]);
  const [adminUsersList, setAdminUsersList] = useState<PlatformUser[]>([]);
  const [adminCompanySearch, setAdminCompanySearch] = useState('');
  const [adminMemberFilterCompId, setAdminMemberFilterCompId] = useState<string>('all');
  const [adminMemberSearch, setAdminMemberSearch] = useState('');

  // SuperAdmin: Provision Organization State
  const [newCompName, setNewCompName] = useState('');
  const [newCompPlan, setNewCompPlan] = useState('team');
  const [newCompSeats, setNewCompSeats] = useState(15);
  const [newCompAdminEmail, setNewCompAdminEmail] = useState('');
  const [newCompAdminName, setNewCompAdminName] = useState('');
  const [newCompActivationLink, setNewCompActivationLink] = useState('');
  const [newCompSubmitting, setNewCompSubmitting] = useState(false);

  // SuperAdmin: Plan Management State
  const [editingPlan, setEditingPlan] = useState<PlanItem | null>(null);
  const [planFormName, setPlanFormName] = useState('');
  const [planFormSlug, setPlanFormSlug] = useState('');
  const [planFormSeats, setPlanFormSeats] = useState(10);
  const [planFormPrice, setPlanFormPrice] = useState('$29/mo');
  const [planFormDesc, setPlanFormDesc] = useState('');
  const [planFormSubmitting, setPlanFormSubmitting] = useState(false);

  // SuperAdmin: Assign Quota Dialog State
  const [quotaTargetComp, setQuotaTargetComp] = useState<CompanyItem | null>(null);
  const [quotaEditPlan, setQuotaEditPlan] = useState('team');
  const [quotaEditSeats, setQuotaEditSeats] = useState(15);

  // SuperAdmin: Assign User Dialog State
  const [assignTargetUser, setAssignTargetUser] = useState<PlatformUser | null>(null);
  const [assignTargetCompId, setAssignTargetCompId] = useState('');
  const [assignTargetRole, setAssignTargetRole] = useState('member');

  // SuperAdmin: KeepAlive State
  const [keepAliveData, setKeepAliveData] = useState<{
    enabled: boolean;
    interval_seconds: number;
    target_url: string;
    total_pings: number;
    successful_pings: number;
    last_ping_latency_ms: number;
    last_ping_time: string;
  } | null>(null);
  const [pingLoading, setPingLoading] = useState(false);

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
  const [canvasBg, setCanvasBg] = useState<'checker' | 'white' | 'dark' | 'navy'>('checker');
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
        if (data.user.is_superadmin) {
          loadSuperAdminData();
        }
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

    // Check for Invitation Activation Token in URL (?token=... or #activate?token=...)
    if (typeof window !== 'undefined') {
      const urlParams = new URLSearchParams(window.location.search);
      let token = urlParams.get('token');
      if (!token && window.location.hash) {
        const hashStr = window.location.hash.replace(/^#\/?/, '');
        const hashParams = new URLSearchParams(hashStr.includes('?') ? hashStr.split('?')[1] : hashStr);
        token = hashParams.get('token');
      }
      if (token) {
        setActivationToken(token);
        loadInvitationDetails(token);
      }
    }
  }, [checkAuth]);

  // Load Invitation Details for Activation
  const loadInvitationDetails = async (token: string) => {
    try {
      const res = await fetch(`/api/auth/invitation_details?token=${encodeURIComponent(token)}`);
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        setActivationDetails(data);
        if (data.full_name) setActivationFullName(data.full_name);
        setShowActivationModal(true);
      } else {
        setActivationError(data.message || 'Invitation is invalid or has expired.');
        setShowActivationModal(true);
      }
    } catch {
      setActivationError('Could not verify invitation token with server.');
      setShowActivationModal(true);
    }
  };

  // Dedicated Activation Form Handler
  const handleActivationSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (activationPassword !== activationConfirmPassword) {
      setActivationError('Passwords do not match');
      return;
    }
    if (activationPassword.length < 5) {
      setActivationError('Password must be at least 5 characters');
      return;
    }
    setActivationLoading(true);
    setActivationError('');
    try {
      const res = await fetch('/api/auth/activate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token: activationToken,
          password: activationPassword,
          full_name: activationFullName
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        setUser(data.user);
        setShowActivationModal(false);
        showToast(`Welcome ${data.user.full_name}! Seat activated successfully.`);
        if (typeof window !== 'undefined' && window.history.replaceState) {
          window.history.replaceState({}, document.title, window.location.pathname);
        }
      } else {
        setActivationError(data.message || 'Failed to activate invitation token');
      }
    } catch {
      setActivationError('Error connecting to activation server');
    } finally {
      setActivationLoading(false);
    }
  };

  // Load Organization & Team Management Data
  const loadOrgData = async () => {
    setOrgDataLoading(true);
    try {
      const [resOverview, resMembers, resInv] = await Promise.all([
        fetch('/api/org/overview'),
        fetch('/api/org/members'),
        fetch('/api/org/invitations')
      ]);

      if (resOverview.ok) {
        const data = await resOverview.json();
        if (data.company) {
          setUser(prev => prev ? { ...prev, company: data.company } : prev);
        }
      }

      if (resMembers.ok) {
        const data = await resMembers.json();
        setOrgMembers(data.members || []);
      }

      if (resInv.ok) {
        const data = await resInv.json();
        setOrgInvitations(data.invitations || []);
      }
    } catch (e) {
      console.warn('Failed to load organization data:', e);
    } finally {
      setOrgDataLoading(false);
    }
  };

  // Promote / Demote Member Role
  const handleUpdateMemberRole = async (userId: string, newRole: 'company_admin' | 'member') => {
    setOrgActionLoading(true);
    try {
      const res = await fetch('/api/org/members/update_role', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, role: newRole })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        showToast(data.message || 'Role updated successfully');
        loadOrgData();
      } else {
        showToast(data.message || 'Failed to update role');
      }
    } catch {
      showToast('Network error updating member role');
    } finally {
      setOrgActionLoading(false);
    }
  };

  // Remove Member from Organization
  const handleRemoveMember = async (userId: string, email: string) => {
    if (!confirm(`Are you sure you want to remove ${email} from this organization? Their seat will be freed immediately.`)) return;
    setOrgActionLoading(true);
    try {
      const res = await fetch('/api/org/members/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        showToast(`User ${email} removed from organization.`);
        loadOrgData();
      } else {
        showToast(data.message || 'Failed to remove user');
      }
    } catch {
      showToast('Error removing member from organization');
    } finally {
      setOrgActionLoading(false);
    }
  };

  // Send Organization Member Invitation
  const handleCreateOrgInvitation = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteEmail.trim()) return;
    setOrgActionLoading(true);
    try {
      const res = await fetch('/api/org/invitations/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: inviteEmail.trim(),
          full_name: inviteName.trim(),
          role: inviteRole
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        const fullActivationUrl = window.location.origin + data.activation_url;
        setInviteLink(fullActivationUrl);
        showToast(`Invitation created for ${inviteEmail.trim()}!`);
        setInviteEmail('');
        setInviteName('');
        setOrgHubTab('invitations');
        loadOrgData();
      } else {
        showToast(data.message || 'Invitation failed');
      }
    } catch {
      showToast('Error creating invitation');
    } finally {
      setOrgActionLoading(false);
    }
  };

  // Revoke Organization Invitation
  const handleRevokeInvitation = async (invitationId: string) => {
    if (!confirm('Revoke this invitation? The token will become invalid and the reserved seat will be restored immediately.')) return;
    setOrgActionLoading(true);
    try {
      const res = await fetch('/api/org/invitations/revoke', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ invitation_id: invitationId })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        showToast('Invitation revoked. Seat restored.');
        loadOrgData();
      } else {
        showToast(data.message || 'Failed to revoke invitation');
      }
    } catch {
      showToast('Error revoking invitation');
    } finally {
      setOrgActionLoading(false);
    }
  };

  // Resend / Refresh Invitation
  const handleResendInvitation = async (invitationId: string) => {
    setOrgActionLoading(true);
    try {
      const res = await fetch('/api/org/invitations/resend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ invitation_id: invitationId })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        const fullLink = window.location.origin + data.activation_url;
        try {
          await navigator.clipboard.writeText(fullLink);
          showToast('Invitation renewed and activation link copied to clipboard!');
        } catch {
          showToast('Invitation renewed! Link: ' + fullLink);
        }
        loadOrgData();
      } else {
        showToast(data.message || 'Failed to refresh invitation');
      }
    } catch {
      showToast('Error refreshing invitation');
    } finally {
      setOrgActionLoading(false);
    }
  };

  // Quick Role Switching for Instant QA/Testing
  const handleQuickSwitchRole = async (targetEmail: string) => {
    setLoadingOverlay(`Switching account to ${targetEmail}...`);
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: targetEmail, password: 'admin' })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        setUser(data.user);
        setShowRoleSwitcher(false);
        showToast(`Logged in as ${data.user.full_name} (${data.user.role})`);
        if (data.user.is_superadmin) {
          loadSuperAdminData();
        }
      } else {
        showToast(data.message || 'Quick switch failed');
      }
    } catch {
      showToast('Error switching account');
    } finally {
      setLoadingOverlay(null);
    }
  };

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


  // Load SuperAdmin Fleet Data
  const loadSuperAdminData = async () => {
    try {
      // 1. Load Companies & Metrics
      const resStats = await fetch('/api/admin/dashboard_stats');
      if (resStats.ok) {
        const data = await resStats.json();
        if (data.metrics?.companies) {
          setAdminCompaniesList(data.metrics.companies);
        }
      }

      // 2. Load Plans
      const resPlans = await fetch('/api/plans');
      if (resPlans.ok) {
        const data = await resPlans.json();
        if (data.plans) {
          setAdminPlansList(data.plans);
        }
      }

      // 3. Load Users
      const resUsers = await fetch('/api/company/users/list');
      if (resUsers.ok) {
        const data = await resUsers.json();
        if (data.users) {
          setAdminUsersList(data.users);
        }
      }

      // 4. Load KeepAlive
      const resKa = await fetch('/api/keep_alive/status');
      if (resKa.ok) {
        const data = await resKa.json();
        setKeepAliveData(data);
      }
    } catch (e) {
      console.warn('Failed to load SuperAdmin fleet data:', e);
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
        if (data.user.is_superadmin) {
          loadSuperAdminData();
        }
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
    setLoadingOverlay('Freeing RAM memory cache and temporary files...');
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

  // ==========================================
  // SuperAdmin Operations
  // ==========================================
  const handleCreateCompanySubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCompName.trim()) return;
    setNewCompSubmitting(true);
    try {
      const res = await fetch('/api/admin/companies/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newCompName.trim(),
          plan: newCompPlan,
          max_seats: newCompSeats,
          admin_email: newCompAdminEmail.trim(),
          admin_name: newCompAdminName.trim()
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        showToast(`Organization '${newCompName}' created successfully!`);
        if (data.activation_url) {
          setNewCompActivationLink(window.location.origin + data.activation_url);
        }
        setNewCompName('');
        setNewCompAdminEmail('');
        setNewCompAdminName('');
        loadSuperAdminData();
      } else {
        showToast(data.message || 'Could not provision organization');
      }
    } catch {
      showToast('Server error creating company');
    } finally {
      setNewCompSubmitting(false);
    }
  };

  const handleUpdateCompanyQuota = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!quotaTargetComp) return;
    try {
      const res = await fetch('/api/admin/companies/update_plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          company_id: quotaTargetComp.id,
          plan: quotaEditPlan,
          max_seats: quotaEditSeats
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        showToast(`Updated quota for ${quotaTargetComp.name}!`);
        setQuotaTargetComp(null);
        loadSuperAdminData();
      } else {
        showToast(data.message || 'Failed to update quota');
      }
    } catch {
      showToast('Error updating organization quota');
    }
  };

  const handleDeleteCompany = async (companyId: string, companyName: string) => {
    if (!window.confirm(`Are you sure you want to delete organization '${companyName}'? All members will be unlinked.`)) return;
    try {
      const res = await fetch('/api/admin/companies/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ company_id: companyId })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        showToast(`Deleted organization '${companyName}'`);
        loadSuperAdminData();
      } else {
        showToast(data.message || 'Failed to delete company');
      }
    } catch {
      showToast('Error deleting company');
    }
  };

  const handleSavePlanSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!planFormName.trim()) return;
    setPlanFormSubmitting(true);
    try {
      const endpoint = editingPlan ? '/api/admin/plans/update' : '/api/admin/plans/create';
      const body = editingPlan ? {
        plan_id: editingPlan.id,
        name: planFormName.trim(),
        default_max_seats: planFormSeats,
        price_monthly: planFormPrice.trim(),
        description: planFormDesc.trim()
      } : {
        name: planFormName.trim(),
        slug: planFormSlug.trim() || undefined,
        default_max_seats: planFormSeats,
        price_monthly: planFormPrice.trim(),
        description: planFormDesc.trim()
      };

      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        showToast(editingPlan ? `Plan '${planFormName}' updated!` : `Plan '${planFormName}' created!`);
        setEditingPlan(null);
        setPlanFormName('');
        setPlanFormSlug('');
        setPlanFormSeats(10);
        setPlanFormPrice('$29/mo');
        setPlanFormDesc('');
        loadSuperAdminData();
      } else {
        showToast(data.message || 'Failed to save plan');
      }
    } catch {
      showToast('Error saving plan');
    } finally {
      setPlanFormSubmitting(false);
    }
  };

  const handleDeletePlan = async (planId: string, planName: string) => {
    if (!window.confirm(`Are you sure you want to delete plan tier '${planName}'?`)) return;
    try {
      const res = await fetch('/api/admin/plans/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_id: planId })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        showToast(`Plan '${planName}' deleted!`);
        loadSuperAdminData();
      } else {
        showToast(data.message || 'Failed to delete plan');
      }
    } catch {
      showToast('Error deleting plan');
    }
  };

  const handleAssignUserCompanySubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!assignTargetUser) return;
    try {
      const res = await fetch('/api/admin/users/assign_company', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: assignTargetUser.id,
          company_id: assignTargetCompId || null,
          role: assignTargetRole
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        showToast(`Assigned ${assignTargetUser.email} successfully!`);
        setAssignTargetUser(null);
        loadSuperAdminData();
      } else {
        showToast(data.message || 'Failed to assign user');
      }
    } catch {
      showToast('Error assigning user');
    }
  };

  const handleRemoveUserFromCompany = async (userId: string, userEmail: string) => {
    if (!window.confirm(`Remove user ${userEmail} from their organization?`)) return;
    try {
      const res = await fetch('/api/company/users/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        showToast(`User ${userEmail} removed from organization.`);
        loadSuperAdminData();
      } else {
        showToast(data.message || 'Failed to remove user');
      }
    } catch {
      showToast('Error removing user');
    }
  };

  const handleTestPingNow = async () => {
    setPingLoading(true);
    try {
      const res = await fetch('/api/keep_alive/ping_now', { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        showToast(`Edge ping success (${data.latency_ms}ms) -> ${data.target_url}`);
      } else {
        showToast('Ping failed');
      }
      const resKa = await fetch('/api/keep_alive/status');
      if (resKa.ok) setKeepAliveData(await resKa.json());
    } catch {
      showToast('Ping error');
    } finally {
      setPingLoading(false);
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
          // Fallback clean avatar
          const fbCanvas = document.createElement('canvas');
          fbCanvas.width = 600;
          fbCanvas.height = 600;
          const fbCtx = fbCanvas.getContext('2d')!;
          fbCtx.fillStyle = '#f8fafc';
          fbCtx.fillRect(0, 0, 600, 600);
          fbCtx.fillStyle = '#2563eb';
          fbCtx.font = 'bold 96px system-ui';
          fbCtx.textAlign = 'center';
          fbCtx.textBaseline = 'middle';
          fbCtx.fillText(photoName.slice(0, 2).toUpperCase(), 300, 270);
          fbCtx.fillStyle = '#64748b';
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
        showToast('AI Cutout applied! Refine anytime with Recover or Erase.');
      } else {
        showToast(resData.message || 'Cutout failed');
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

  // Filtered Companies for Admin Directory
  const filteredAdminCompanies = adminCompaniesList.filter(c => {
    if (!adminCompanySearch.trim()) return true;
    const q = adminCompanySearch.toLowerCase();
    return (c.name && c.name.toLowerCase().includes(q)) ||
           (c.slug && c.slug.toLowerCase().includes(q)) ||
           (c.plan && c.plan.toLowerCase().includes(q));
  });

  // Filtered Users for Admin Members Tab
  const filteredAdminUsers = adminUsersList.filter(u => {
    if (adminMemberFilterCompId !== 'all') {
      if (adminMemberFilterCompId === 'unassigned') {
        if (u.company_id) return false;
      } else if (u.company_id !== adminMemberFilterCompId) {
        return false;
      }
    }
    if (!adminMemberSearch.trim()) return true;
    const q = adminMemberSearch.toLowerCase();
    return (u.email && u.email.toLowerCase().includes(q)) ||
           (u.full_name && u.full_name.toLowerCase().includes(q));
  });

  // ==========================================
  // RENDER: Clean Light Authentication View
  // ==========================================
  if (authChecking) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f8fafc' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14 }}>
          <div style={{ width: 44, height: 44, borderRadius: 12, background: 'linear-gradient(135deg, #2563eb, #1d4ed8)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 12px rgba(37,99,235,0.25)' }}>
            <Shield size={24} color="#fff" />
          </div>
          <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#64748b' }}>Initializing VeloRoster Pro...</div>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f8fafc', padding: 24 }}>
        <div className="card-clean" style={{ maxWidth: 420, width: '100%', padding: '36px 32px' }}>
          {/* Brand Header */}
          <div style={{ textAlign: 'center', marginBottom: 26 }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 46, height: 46, borderRadius: 12, background: 'linear-gradient(135deg, #2563eb, #1d4ed8)', boxShadow: '0 4px 14px rgba(37,99,235,0.25)', marginBottom: 14 }}>
              <Shield size={22} color="#ffffff" />
            </div>
            <h1 style={{ fontSize: '1.45rem', fontWeight: 800, color: '#0f172a', letterSpacing: '-0.02em' }}>
              VeloRoster <span style={{ color: '#2563eb' }}>Pro</span>
            </h1>
            <div style={{ fontSize: '0.78125rem', fontWeight: 500, color: '#64748b', marginTop: 4 }}>
              Athletic Roster & 180×180 Headshot Studio
            </div>
          </div>

          {/* Clean Segmented Tab Switch */}
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 22 }}>
            <div className="segmented-track" style={{ width: '100%' }}>
              <button
                type="button"
                className={`segmented-btn ${authTab === 'login' ? 'active' : ''}`}
                style={{ flex: 1 }}
                onClick={() => setAuthTab('login')}
              >
                Sign In
              </button>
              <button
                type="button"
                className={`segmented-btn ${authTab === 'activate' ? 'active' : ''}`}
                style={{ flex: 1 }}
                onClick={() => setAuthTab('activate')}
              >
                Activate Seat
              </button>
            </div>
          </div>

          {authError && (
            <div style={{ padding: '10px 14px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, color: '#dc2626', fontSize: '0.8125rem', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
              <AlertCircle size={16} />
              <span>{authError}</span>
            </div>
          )}

          {authTab === 'login' ? (
            <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>Corporate Email or Username</label>
                <input
                  type="text"
                  className="input-ui"
                  placeholder="enterprise@ecstaticloud.com"
                  value={authEmail}
                  onChange={e => setAuthEmail(e.target.value)}
                  required
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>Password</label>
                <input
                  type="password"
                  className="input-ui"
                  placeholder="••••••••"
                  value={authPassword}
                  onChange={e => setAuthPassword(e.target.value)}
                  required
                />
              </div>
              <button
                type="submit"
                disabled={authSubmitting}
                className="btn-ui btn-primary"
                style={{ padding: '10px 0', marginTop: 4, height: 42 }}
              >
                {authSubmitting ? 'Authenticating...' : 'Sign In to Workspace'}
              </button>
            </form>
          ) : (
            <form onSubmit={handleActivateInvite} style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>Invitation Token</label>
                <input
                  type="text"
                  className="input-ui"
                  placeholder="Paste 32-character invite token"
                  value={authInviteToken}
                  onChange={e => setAuthInviteToken(e.target.value)}
                  required
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>Your Full Name</label>
                <input
                  type="text"
                  className="input-ui"
                  placeholder="Jordan Miller"
                  value={authName}
                  onChange={e => setAuthName(e.target.value)}
                  required
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>Create Password</label>
                <input
                  type="password"
                  className="input-ui"
                  placeholder="Minimum 6 characters"
                  value={authPassword}
                  onChange={e => setAuthPassword(e.target.value)}
                  required
                />
              </div>
              <button
                type="submit"
                disabled={authSubmitting}
                className="btn-ui btn-primary"
                style={{ padding: '10px 0', marginTop: 4, height: 42 }}
              >
                {authSubmitting ? 'Activating...' : 'Activate Seat'}
              </button>
            </form>
          )}

          <div style={{ marginTop: 22, fontSize: '0.72rem', color: '#94a3b8', textAlign: 'center', lineHeight: 1.5 }}>
            Ecstaticloud Technologies &bull; Commercial Edition &bull; 0 Cloud Storage Footprint
          </div>
        </div>
      </div>
    );
  }

  // ==========================================
  // RENDER: Authenticated Light Application
  // ==========================================
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-app)' }}>
      {/* Toast Notification */}
      {toastMsg && (
        <div className="toast-clean">
          <Sparkles size={16} color="#2563eb" />
          <span>{toastMsg}</span>
        </div>
      )}

      {/* Loading Overlay */}
      {loadingOverlay && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(255,255,255,0.85)', backdropFilter: 'blur(6px)', zIndex: 99999, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 14 }}>
          <div style={{ width: 38, height: 38, border: '3px solid #e2e8f0', borderTopColor: '#2563eb', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
          <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#0f172a' }}>{loadingOverlay}</div>
          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      )}

      {/* Unified Clean Light Navbar */}
      <header style={{ height: 60, borderBottom: '1px solid var(--border-default)', background: '#ffffff', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px', position: 'sticky', top: 0, zIndex: 50 }}>
        {/* Left: Brand & Tenant Identity */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }} onClick={() => setCurrentScreen('landing')}>
            <div style={{ width: 32, height: 32, borderRadius: 8, background: 'linear-gradient(135deg, #2563eb, #1d4ed8)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 2px 6px rgba(37,99,235,0.25)' }}>
              <Shield size={18} color="#fff" />
            </div>
            <div>
              <div style={{ fontSize: '0.95rem', fontWeight: 800, color: '#0f172a', letterSpacing: '-0.02em', lineHeight: 1.1 }}>
                VeloRoster <span style={{ color: '#2563eb' }}>Pro</span>
              </div>
              <div style={{ fontSize: '0.625rem', fontWeight: 600, color: '#64748b', letterSpacing: '0.04em' }}>
                180×180 STUDIO
              </div>
            </div>
          </div>

          {/* Company Badge */}
          {user.company && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '3px 10px', background: '#f8fafc', borderRadius: 'var(--radius-full)', border: '1px solid #e2e8f0' }}>
              <Building size={13} color="#64748b" />
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#334155' }}>{user.company.name}</span>
              <span style={{ fontSize: '0.65rem', padding: '1px 6px', borderRadius: 4, background: '#eff6ff', color: '#2563eb', fontWeight: 700, textTransform: 'uppercase' }}>
                {user.company.plan}
              </span>
              <span style={{ fontSize: '0.72rem', color: '#64748b' }}>&bull; {user.company.used_seats}/{user.company.max_seats} Seats</span>
            </div>
          )}

          {/* RBAC Role Badges */}
          {user.role === 'superadmin' ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '3px 10px', background: '#f5f3ff', border: '1px solid #ddd6fe', borderRadius: 'var(--radius-full)' }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#8b5cf6' }} />
              <span style={{ fontSize: '0.72rem', fontWeight: 700, color: '#7c3aed' }}>👑 Platform SuperAdmin</span>
            </div>
          ) : user.role === 'company_admin' ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '3px 10px', background: '#ecfdf5', border: '1px solid #a7f3d0', borderRadius: 'var(--radius-full)' }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#059669' }} />
              <span style={{ fontSize: '0.72rem', fontWeight: 700, color: '#047857' }}>🛡️ Org Administrator</span>
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '3px 10px', background: '#f1f5f9', border: '1px solid #cbd5e1', borderRadius: 'var(--radius-full)' }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#64748b' }} />
              <span style={{ fontSize: '0.72rem', fontWeight: 700, color: '#475569' }}>👤 Team Member</span>
            </div>
          )}
        </div>

        {/* Right: Unified Action Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {/* SuperAdmin Hub (Platform Root Only) */}
          {user.is_superadmin && (
            <button
              className="btn-ui btn-secondary"
              style={{ fontSize: '0.75rem', padding: '6px 12px', border: '1px solid #ddd6fe', background: '#faf5ff', color: '#6d28d9' }}
              onClick={() => {
                loadSuperAdminData();
                setShowPlatformDashboard(true);
              }}
            >
              <Building size={14} color="#7c3aed" />
              <span style={{ fontWeight: 700 }}>SuperAdmin Hub</span>
            </button>
          )}

          {/* Organization & Team Management (Company Admin & SuperAdmin) */}
          {(user.is_superadmin || user.is_company_admin || user.can_manage_team) && (
            <button
              className="btn-ui btn-secondary"
              style={{ fontSize: '0.75rem', padding: '6px 12px', border: '1px solid #bbf7d0', background: '#f0fdf4', color: '#15803d' }}
              onClick={() => {
                loadOrgData();
                setShowOrgHub(true);
              }}
            >
              <Users size={14} color="#16a34a" />
              <span style={{ fontWeight: 700 }}>Team & Organization</span>
            </button>
          )}

          {/* Quick Role Switcher for QA / Live Testing */}
          <div style={{ position: 'relative' }}>
            <button
              className="btn-ui btn-secondary"
              style={{ fontSize: '0.75rem', padding: '6px 11px', border: '1px solid #e2e8f0', background: '#ffffff' }}
              onClick={() => setShowRoleSwitcher(!showRoleSwitcher)}
              title="Quickly switch between seeded roles to test RBAC workflows"
            >
              <Zap size={13} color="#f59e0b" />
              <span style={{ fontWeight: 600 }}>Test Roles</span>
            </button>

            {showRoleSwitcher && (
              <div
                style={{
                  position: 'absolute',
                  top: '115%',
                  right: 0,
                  width: 270,
                  background: '#ffffff',
                  border: '1px solid #e2e8f0',
                  borderRadius: 10,
                  boxShadow: '0 10px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.05)',
                  padding: 8,
                  zIndex: 200
                }}
              >
                <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#64748b', padding: '4px 8px 6px', borderBottom: '1px solid #f1f5f9', textTransform: 'uppercase' }}>
                  RBAC Impersonation Suite
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
                  <button
                    className="btn-ui btn-ghost"
                    style={{ justifyContent: 'flex-start', padding: '7px 8px', fontSize: '0.75rem', textAlign: 'left', borderRadius: 6 }}
                    onClick={() => handleQuickSwitchRole('enterprise@ecstaticloud.com')}
                  >
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
                      <span style={{ fontWeight: 700, color: '#7c3aed' }}>👑 SuperAdmin</span>
                      <span style={{ fontSize: '0.6875rem', color: '#64748b' }}>enterprise@ecstaticloud.com</span>
                    </div>
                  </button>
                  <button
                    className="btn-ui btn-ghost"
                    style={{ justifyContent: 'flex-start', padding: '7px 8px', fontSize: '0.75rem', textAlign: 'left', borderRadius: 6 }}
                    onClick={() => handleQuickSwitchRole('admin@test.in')}
                  >
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
                      <span style={{ fontWeight: 700, color: '#059669' }}>🛡️ Org Admin</span>
                      <span style={{ fontSize: '0.6875rem', color: '#64748b' }}>admin@test.in (Test 1)</span>
                    </div>
                  </button>
                  <button
                    className="btn-ui btn-ghost"
                    style={{ justifyContent: 'flex-start', padding: '7px 8px', fontSize: '0.75rem', textAlign: 'left', borderRadius: 6 }}
                    onClick={() => handleQuickSwitchRole('photographer@test.in')}
                  >
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
                      <span style={{ fontWeight: 700, color: '#475569' }}>👤 Team Member</span>
                      <span style={{ fontSize: '0.6875rem', color: '#64748b' }}>photographer@test.in (Test 1)</span>
                    </div>
                  </button>
                </div>
              </div>
            )}
          </div>

          <button
            className="btn-ui btn-danger"
            style={{ fontSize: '0.75rem', padding: '6px 12px' }}
            onClick={handleFreeRAM}
            title="Purge RAM memory cache & clear temporary disk"
          >
            <Cpu size={14} />
            <span>Free RAM</span>
          </button>

          {/* Profile & Logout */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingLeft: 8, borderLeft: '1px solid #e2e8f0' }}>
            <div style={{ width: 30, height: 30, borderRadius: '50%', background: '#eff6ff', border: '1px solid #bfdbfe', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75rem', fontWeight: 700, color: '#2563eb' }}>
              {user.full_name ? user.full_name.slice(0, 2).toUpperCase() : 'AD'}
            </div>
            <button
              className="btn-ui btn-ghost"
              style={{ padding: '6px' }}
              onClick={handleLogout}
              title="Sign Out"
            >
              <LogOut size={15} />
            </button>
          </div>
        </div>
      </header>

      {/* ========================================================= */}
      {/* SCREEN 1: UNIFIED LANDING WORKFLOW */}
      {/* ========================================================= */}
      {currentScreen === 'landing' ? (
        <main style={{ flex: 1, maxWidth: 980, width: '100%', margin: '0 auto', padding: '40px 20px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          {/* Hero Header */}
          <div style={{ textAlign: 'center', marginBottom: 30 }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 14px', borderRadius: 'var(--radius-full)', background: '#eff6ff', border: '1px solid #bfdbfe', marginBottom: 14 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#2563eb' }} />
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#1d4ed8' }}>Standardized 180×180 Transparent Headshots &bull; 0 Cloud Storage</span>
            </div>
            <h1 style={{ fontSize: '2.25rem', fontWeight: 800, color: '#0f172a', letterSpacing: '-0.025em', lineHeight: 1.2 }}>
              Athletic Roster & <span style={{ color: '#2563eb' }}>Headshot Studio</span>
            </h1>
            <p style={{ fontSize: '0.9375rem', color: '#475569', marginTop: 10, maxWidth: 640 }}>
              Search athletes across global archives, scrape team rosters, or batch process local folders with automatic face centering and background removal.
            </p>
          </div>

          {/* Unified 3-Tab Segmented Control (Apple / Linear style) */}
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 24, width: '100%', maxWidth: 640 }}>
            <div className="segmented-track" style={{ width: '100%' }}>
              <button
                className={`segmented-btn ${activeWorkflow === 'athlete' ? 'active' : ''}`}
                style={{ flex: 1 }}
                onClick={() => setActiveWorkflow('athlete')}
              >
                <Search size={14} />
                <span>Single Athlete Search</span>
              </button>
              <button
                className={`segmented-btn ${activeWorkflow === 'url' ? 'active' : ''}`}
                style={{ flex: 1 }}
                onClick={() => setActiveWorkflow('url')}
              >
                <Globe size={14} />
                <span>Team Roster Website URL</span>
              </button>
              <button
                className={`segmented-btn ${activeWorkflow === 'local' ? 'active' : ''}`}
                style={{ flex: 1 }}
                onClick={() => setActiveWorkflow('local')}
              >
                <Folder size={14} />
                <span>Local Photo Folder</span>
              </button>
            </div>
          </div>

          {/* WORKFLOW 1: SINGLE ATHLETE SEARCH */}
          {activeWorkflow === 'athlete' && (
            <div className="card-clean" style={{ width: '100%', padding: 32 }}>
              <div style={{ fontSize: '0.8125rem', fontWeight: 700, color: '#2563eb', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 18, display: 'flex', alignItems: 'center', gap: 8 }}>
                <Search size={16} />
                <span>Search Athlete with Strict Team & Era Matching</span>
              </div>

              {/* Form Input Controls */}
              <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1.2fr 1.4fr', gap: 14, marginBottom: 16 }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 6 }}>Player Name (Required)</label>
                  <input
                    type="text"
                    className="input-ui"
                    value={searchPlayerName}
                    onChange={e => setSearchPlayerName(e.target.value)}
                    placeholder="e.g. LeBron James, Wayne Gretzky"
                    onKeyDown={e => e.key === 'Enter' && handleSearchAthlete()}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 6 }}>Team Name (Strict Filter)</label>
                  <input
                    type="text"
                    className="input-ui"
                    value={searchTeamName}
                    onChange={e => setSearchTeamName(e.target.value)}
                    placeholder="e.g. Miami Heat, Rangers"
                    onKeyDown={e => e.key === 'Enter' && handleSearchAthlete()}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 6 }}>Destination Folder</label>
                  <input
                    type="text"
                    className="input-ui"
                    value={searchDestinationFolder}
                    onChange={e => setSearchDestinationFolder(e.target.value)}
                    placeholder="Miami Heat - LeBron James"
                    onKeyDown={e => e.key === 'Enter' && handleSearchAthlete()}
                  />
                </div>
              </div>

              {/* Action Button & Preset Chips */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 20 }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
                  <span style={{ fontSize: '0.72rem', fontWeight: 700, color: '#64748b' }}>Verified Stints:</span>
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
                      className="preset-chip"
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

                <button
                  className="btn-ui btn-primary"
                  style={{ height: 40, padding: '0 20px' }}
                  onClick={handleSearchAthlete}
                  disabled={searchLoading}
                >
                  <Search size={15} />
                  <span>{searchLoading ? 'Searching Archives...' : 'Search Portraits'}</span>
                </button>
              </div>

              {/* Results */}
              {searchPlayerOptions.length > 0 && (
                <div style={{ marginTop: 20, paddingTop: 20, borderTop: '1px solid var(--border-default)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                    <div style={{ fontSize: '0.875rem', fontWeight: 700, color: '#0f172a' }}>
                      Verified Stints & High-Res Portraits ({searchPlayerOptions.length}):
                    </div>
                    <span style={{ fontSize: '0.75rem', color: '#64748b' }}>Click a stint card to select</span>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12, marginBottom: 20 }}>
                    {searchPlayerOptions.map((opt, idx) => (
                      <div
                        key={idx}
                        onClick={() => setSelectedPhotoOptionIdx(idx)}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 12,
                          padding: 12,
                          borderRadius: 'var(--radius-md)',
                          background: selectedPhotoOptionIdx === idx ? '#eff6ff' : '#ffffff',
                          border: `1.5px solid ${selectedPhotoOptionIdx === idx ? '#2563eb' : '#e2e8f0'}`,
                          cursor: 'pointer',
                          transition: 'all 0.15s ease',
                          boxShadow: selectedPhotoOptionIdx === idx ? '0 0 0 1px #2563eb' : 'var(--shadow-xs)'
                        }}
                      >
                        <img
                          src={opt.image ? `/api/proxy_photo?url=${encodeURIComponent(opt.image)}&width=200` : ''}
                          alt={opt.team}
                          style={{ width: 54, height: 54, borderRadius: 8, objectFit: 'cover', background: '#f1f5f9' }}
                          onError={(e) => { (e.target as HTMLElement).style.opacity = '0.2'; }}
                        />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: '0.84375rem', fontWeight: 700, color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {opt.team}
                          </div>
                          <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: 2 }}>
                            {opt.years || 'Era active'} {opt.jersey ? `&bull; #${opt.jersey}` : ''}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                    <button
                      className="btn-ui btn-primary"
                      style={{ padding: '10px 24px', fontSize: '0.875rem', height: 42 }}
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
            <div className="card-clean" style={{ width: '100%', padding: 32 }}>
              <div style={{ fontSize: '0.8125rem', fontWeight: 700, color: '#2563eb', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 18, display: 'flex', alignItems: 'center', gap: 8 }}>
                <Globe size={16} />
                <span>Full League Team Roster Ingestion (Proballers, Eurobasket, NHL, EIHL, NCAA)</span>
              </div>

              {/* Form Input Row */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 240px auto', gap: 14, alignItems: 'end', marginBottom: 16 }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 6 }}>Team Roster Website URL</label>
                  <input
                    type="text"
                    className="input-ui"
                    value={rosterUrl}
                    onChange={e => setRosterUrl(e.target.value)}
                    placeholder="https://www.cardiffdevils.com/team/ or Proballers URL"
                    onKeyDown={e => e.key === 'Enter' && handleFetchTeamRoster()}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 6 }}>Destination Folder</label>
                  <input
                    type="text"
                    className="input-ui"
                    value={rosterFolder}
                    onChange={e => setRosterFolder(e.target.value)}
                    placeholder="Cardiff Devils"
                    onKeyDown={e => e.key === 'Enter' && handleFetchTeamRoster()}
                  />
                </div>
                <button
                  className="btn-ui btn-primary"
                  style={{ height: 40, padding: '0 20px' }}
                  onClick={handleFetchTeamRoster}
                  disabled={rosterLoading}
                >
                  <Globe size={15} />
                  <span>{rosterLoading ? 'Scraping...' : 'Fetch Roster'}</span>
                </button>
              </div>

              {/* Supported Presets Chips */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 20 }}>
                <span style={{ fontSize: '0.72rem', fontWeight: 700, color: '#64748b' }}>Supported Presets:</span>
                {[
                  { name: 'Cardiff Devils (EIHL)', url: 'https://www.cardiffdevils.com/team/', folder: 'Cardiff Devils' },
                  { name: 'Buffalo Sabres (NHL)', url: 'https://www.nhl.com/sabres/roster', folder: 'Buffalo Sabres' },
                  { name: 'Caen U21 (Proballers)', url: 'https://www.proballers.com/basketball/team/15352/caen-u21/roster', folder: 'Caen U21' },
                  { name: 'Debreceni Egyetem (Eurobasket)', url: 'https://basketball.eurobasket.com/team/Debreceni-Egyetem/1833/Roster/2026-2027#google_vignette', folder: 'Debreceni Egyetem' }
                ].map((preset, idx) => (
                  <button
                    key={idx}
                    type="button"
                    className="preset-chip"
                    onClick={() => {
                      setRosterUrl(preset.url);
                      setRosterFolder(preset.folder);
                    }}
                  >
                    {preset.name}
                  </button>
                ))}
              </div>

              {/* Roster Table */}
              {rosterPlayers.length > 0 && (
                <div style={{ marginTop: 20, paddingTop: 20, borderTop: '1px solid var(--border-default)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>{rosterFolder}</span>
                      <span style={{ fontSize: '0.72rem', padding: '2px 8px', borderRadius: 'var(--radius-full)', background: '#eff6ff', color: '#2563eb', fontWeight: 700 }}>
                        {rosterPlayers.length} Players
                      </span>
                    </div>

                    <div style={{ display: 'flex', gap: 8 }}>
                      <button
                        className="btn-ui btn-secondary"
                        style={{ fontSize: '0.75rem', padding: '5px 12px' }}
                        onClick={handleCopyForSheets}
                      >
                        <Copy size={13} />
                        <span>Copy for Sheets</span>
                      </button>
                      <button
                        className="btn-ui btn-secondary"
                        style={{ fontSize: '0.75rem', padding: '5px 12px' }}
                        onClick={() => setBulkPasteOpen(!bulkPasteOpen)}
                      >
                        <FileSpreadsheet size={13} />
                        <span>Bulk Paste IDs</span>
                      </button>
                    </div>
                  </div>

                  {bulkPasteOpen && (
                    <div style={{ background: '#f8fafc', padding: 14, borderRadius: 10, border: '1px solid #e2e8f0', marginBottom: 14 }}>
                      <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 6 }}>
                        Paste Name &lt;Tab&gt; Number from Google Sheets or Excel:
                      </div>
                      <textarea
                        rows={3}
                        className="input-ui"
                        placeholder="Marcus Meeks&#9;882177&#10;Braeden Elnicki&#9;1947454..."
                        value={bulkPasteText}
                        onChange={e => setBulkPasteText(e.target.value)}
                        style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', height: 'auto', padding: 10 }}
                      />
                      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 10 }}>
                        <button className="btn-ui btn-secondary" style={{ fontSize: '0.75rem' }} onClick={() => setBulkPasteOpen(false)}>Cancel</button>
                        <button className="btn-ui btn-primary" style={{ fontSize: '0.75rem' }} onClick={handleApplyBulkPaste}>Apply to Table</button>
                      </div>
                    </div>
                  )}

                  <div style={{ maxHeight: 360, overflowY: 'auto', border: '1px solid var(--border-default)', borderRadius: 10, marginBottom: 20 }}>
                    <table className="table-clean">
                      <thead>
                        <tr>
                          <th style={{ width: 50 }}>Avatar</th>
                          <th>Athlete Name</th>
                          <th style={{ width: 50, textAlign: 'center' }}>#</th>
                          <th style={{ width: 70, textAlign: 'center' }}>Pos</th>
                          <th style={{ width: 140 }}>Assigned ID</th>
                          <th style={{ width: 150 }}>Resulting File</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rosterPlayers.map((player, idx) => (
                          <tr key={idx}>
                            <td>
                              <img
                                src={player.image ? `/api/proxy_photo?url=${encodeURIComponent(player.image)}&width=100` : ''}
                                alt={player.name}
                                style={{ width: 34, height: 34, borderRadius: 6, objectFit: 'cover', background: '#f1f5f9' }}
                                onError={(e) => { (e.target as HTMLElement).style.opacity = '0.2'; }}
                              />
                            </td>
                            <td style={{ fontWeight: 600, color: '#0f172a' }}>{player.name}</td>
                            <td style={{ textAlign: 'center', color: '#64748b' }}>{player.jersey || '-'}</td>
                            <td style={{ textAlign: 'center', color: '#64748b' }}>{player.position || player.pos || '-'}</td>
                            <td>
                              <input
                                type="text"
                                className="input-ui"
                                style={{ height: 28, padding: '0 8px', fontSize: '0.75rem' }}
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
                            <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: '#0284c7' }}>
                              {player.assigned_number ? `${player.assigned_number}.png` : (player.jersey ? `${player.jersey}.png` : `${player.name}.png`)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                    <button
                      className="btn-ui btn-primary"
                      style={{ padding: '10px 24px', fontSize: '0.875rem', height: 42 }}
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
            <div className="card-clean" style={{ width: '100%', padding: 32 }}>
              {/* Clean Light Dropzone */}
              <div className="dropzone-clean" style={{ marginBottom: 24 }}>
                <div style={{ width: 52, height: 52, borderRadius: 14, background: '#eff6ff', border: '1px solid #bfdbfe', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#2563eb' }}>
                  <Folder size={26} />
                </div>
                <div>
                  <div style={{ fontSize: '1rem', fontWeight: 700, color: '#0f172a' }}>
                    Choose Photo Folder from Your Computer
                  </div>
                  <div style={{ fontSize: '0.8125rem', color: '#64748b', marginTop: 4 }}>
                    Select an entire folder using native webkit directory picker
                  </div>
                </div>
                <div>
                  <label className="btn-ui btn-primary" style={{ cursor: 'pointer', height: 40, padding: '0 20px' }}>
                    <Folder size={16} />
                    <span>Choose Photo Folder</span>
                    <input
                      type="file"
                      // @ts-expect-error webkitdirectory is standard for folder picker
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
              <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 26 }}>
                <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#475569', whiteSpace: 'nowrap' }}>Or enter folder path:</span>
                <input
                  type="text"
                  className="input-ui"
                  placeholder="/Users/.../Downloads/Team_Photos or 1908-Saint Anselm"
                  value={manualPath}
                  onChange={e => setManualPath(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleOpenLocalFolder(manualPath)}
                />
                <button
                  className="btn-ui btn-secondary"
                  style={{ height: 40, padding: '0 18px' }}
                  onClick={() => handleOpenLocalFolder(manualPath)}
                  disabled={folderLoading}
                >
                  Open
                </button>
              </div>

              {/* Detected Folders in Downloads */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                  <div style={{ fontSize: '0.84375rem', fontWeight: 700, color: '#0f172a', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <HardDrive size={16} color="#2563eb" />
                    <span>Detected Photo Folders in Downloads</span>
                    <span style={{ fontSize: '0.6875rem', padding: '1px 7px', borderRadius: 4, background: '#eff6ff', color: '#2563eb', fontWeight: 700 }}>
                      {detectedFolders.length}
                    </span>
                  </div>
                  <button
                    className="btn-ui btn-secondary"
                    style={{ fontSize: '0.72rem', padding: '4px 10px' }}
                    onClick={loadSuggestedFolders}
                  >
                    <RefreshCw size={12} />
                    <span>Refresh</span>
                  </button>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 12 }}>
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
                          background: '#ffffff',
                          border: '1px solid var(--border-default)',
                          cursor: 'pointer',
                          transition: 'all 0.15s ease',
                          boxShadow: 'var(--shadow-xs)'
                        }}
                      >
                        <Folder size={20} color="#2563eb" />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: '0.84375rem', fontWeight: 700, color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {f.name}
                          </div>
                          <div style={{ fontSize: '0.72rem', color: '#64748b', marginTop: 2 }}>
                            {f.count} {f.count === 1 ? 'photo' : 'photos'} &bull; Ready to edit
                          </div>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div style={{ gridColumn: '1 / -1', padding: 24, textAlign: 'center', color: '#94a3b8', fontSize: '0.8125rem' }}>
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
        /* SCREEN 2: UNIFIED STUDIO WORKBENCH (LIGHT THEME) */
        /* ========================================================= */
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: 'calc(100vh - 60px)', overflow: 'hidden' }}>
          {/* Action Header */}
          <div style={{ height: 52, borderBottom: '1px solid var(--border-default)', background: '#ffffff', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              <button
                className="btn-ui btn-secondary"
                style={{ fontSize: '0.75rem', padding: '5px 12px' }}
                onClick={() => setCurrentScreen('landing')}
              >
                <ArrowLeft size={14} />
                <span>Change Folder</span>
              </button>

              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: '0.84375rem', fontWeight: 700, color: '#0f172a' }}>
                  {currentFolder.replaceAll('\\', '/').split('/').filter(Boolean).pop() || currentFolder}
                </span>
                <ChevronRight size={14} color="#94a3b8" />
                <span style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: '#0284c7' }}>
                  {editedFolder.replaceAll('\\', '/').split('/').filter(Boolean).pop() || editedFolder}/
                </span>
              </div>
            </div>

            {/* Photo Counter */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 10px', background: '#f8fafc', borderRadius: 'var(--radius-full)', border: '1px solid #e2e8f0' }}>
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#334155' }}>
                Photo {currentIndex + 1} of {photos.length}
              </span>
              <span style={{ fontSize: '0.72rem', color: '#64748b', fontFamily: 'var(--font-mono)' }}>
                &bull; {photos[currentIndex]}
              </span>
            </div>

            {/* Workbench Top Actions */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button
                className="btn-ui btn-secondary"
                style={{ fontSize: '0.78125rem', padding: '6px 14px' }}
                onClick={handleCutout}
                title="Automated background removal with u2net"
              >
                <Scissors size={14} color="#8b5cf6" />
                <span>AI Cutout</span>
              </button>

              <button
                className="btn-ui btn-secondary"
                style={{ fontSize: '0.78125rem', padding: '6px 14px' }}
                onClick={handleSaveActivePhoto}
                title="Save 180×180 PNG directly"
              >
                <Save size={14} color="#10b981" />
                <span>Save Headshot</span>
              </button>

              <button
                className="btn-ui btn-primary"
                style={{ fontSize: '0.78125rem', padding: '6px 16px' }}
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
            <div style={{ width: 290, borderRight: '1px solid var(--border-default)', background: '#ffffff', padding: 18, display: 'flex', flexDirection: 'column', gap: 16, overflowY: 'auto' }}>
              {/* Tool Mode Segmented Control */}
              <div>
                <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 8 }}>
                  Tool Mode
                </div>
                <div className="segmented-track" style={{ width: '100%' }}>
                  <button
                    className={`segmented-btn ${toolMode === 'frame' ? 'active' : ''}`}
                    style={{ flex: 1, fontSize: '0.75rem', padding: '6px 0' }}
                    onClick={() => setToolMode('frame')}
                  >
                    <Move size={13} />
                    <span>Pan</span>
                  </button>
                  <button
                    className={`segmented-btn ${toolMode === 'recover' ? 'active' : ''}`}
                    style={{ flex: 1, fontSize: '0.75rem', padding: '6px 0' }}
                    onClick={() => setToolMode('recover')}
                  >
                    <Sparkles size={13} />
                    <span>Recover</span>
                  </button>
                  <button
                    className={`segmented-btn ${toolMode === 'erase' ? 'active' : ''}`}
                    style={{ flex: 1, fontSize: '0.75rem', padding: '6px 0' }}
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
                  <div className="card-clean" style={{ padding: 14 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                      <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#475569' }}>Zoom Scale</span>
                      <span style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: '#0284c7', fontWeight: 700 }}>
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
                      style={{ width: '100%', accentColor: '#2563eb', marginBottom: 12 }}
                    />
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                      <button className="btn-ui btn-secondary" style={{ fontSize: '0.75rem', padding: '6px 0' }} onClick={handleAutoAlignCurrent}>Auto-Align Face</button>
                      <button className="btn-ui btn-secondary" style={{ fontSize: '0.75rem', padding: '6px 0' }} onClick={handleCenter}>Center</button>
                      <button className="btn-ui btn-secondary" style={{ fontSize: '0.75rem', padding: '6px 0' }} onClick={handleFitWidth}>Fit Width</button>
                      <button className="btn-ui btn-secondary" style={{ fontSize: '0.75rem', padding: '6px 0' }} onClick={handleFitHeight}>Fit Height</button>
                    </div>
                  </div>

                  <div className="card-clean" style={{ padding: 14 }}>
                    <div style={{ fontSize: '0.78125rem', fontWeight: 700, color: '#0f172a', marginBottom: 4 }}>
                      Batch Team Framing
                    </div>
                    <p style={{ fontSize: '0.72rem', color: '#64748b', lineHeight: 1.4, marginBottom: 10 }}>
                      Apply this photo&apos;s framing to all {photos.length} portraits:
                    </p>
                    <button
                      className="btn-ui btn-secondary"
                      style={{ width: '100%', fontSize: '0.75rem', padding: '7px 0' }}
                      onClick={handleApplyFramingToAll}
                    >
                      <Layers size={14} />
                      <span>Apply Framing to All</span>
                    </button>
                  </div>
                </div>
              ) : (
                /* Mode 2 & 3: Brush Controls */
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <div className="card-clean" style={{ padding: 14 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                      <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#475569' }}>Brush Radius</span>
                      <span style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: '#0284c7', fontWeight: 700 }}>{brushSize} px</span>
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
                      <button className="btn-ui btn-secondary" style={{ flex: 1, fontSize: '0.75rem', padding: '6px 0' }} onClick={handleUndoMask}>Undo Stroke</button>
                      <button className="btn-ui btn-secondary" style={{ flex: 1, fontSize: '0.75rem', padding: '6px 0' }} onClick={handleResetMask}>Reset Mask</button>
                    </div>
                    <p style={{ fontSize: '0.72rem', color: '#64748b', marginTop: 10, lineHeight: 1.4 }}>
                      {toolMode === 'recover'
                        ? 'Recover restores hair/jersey details from original photo.'
                        : 'Erase cleans up background residue.'}
                    </p>
                  </div>
                </div>
              )}

              {/* Canvas Background & Original View */}
              <div className="card-clean" style={{ padding: 14 }}>
                <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 8 }}>
                  Canvas Background
                </div>
                <div className="segmented-track" style={{ width: '100%', marginBottom: 10 }}>
                  <button
                    className={`segmented-btn ${canvasBg === 'checker' ? 'active' : ''}`}
                    style={{ flex: 1, fontSize: '0.72rem', padding: '4px 0' }}
                    onClick={() => setCanvasBg('checker')}
                  >
                    Transparent
                  </button>
                  <button
                    className={`segmented-btn ${canvasBg === 'white' ? 'active' : ''}`}
                    style={{ flex: 1, fontSize: '0.72rem', padding: '4px 0' }}
                    onClick={() => setCanvasBg('white')}
                  >
                    White
                  </button>
                  <button
                    className={`segmented-btn ${canvasBg === 'dark' ? 'active' : ''}`}
                    style={{ flex: 1, fontSize: '0.72rem', padding: '4px 0' }}
                    onClick={() => setCanvasBg('dark')}
                  >
                    Dark
                  </button>
                  <button
                    className={`segmented-btn ${canvasBg === 'navy' ? 'active' : ''}`}
                    style={{ flex: 1, fontSize: '0.72rem', padding: '4px 0' }}
                    onClick={() => setCanvasBg('navy')}
                  >
                    Navy
                  </button>
                </div>

                <button
                  className="btn-ui btn-secondary"
                  style={{ width: '100%', fontSize: '0.75rem', padding: '6px 0', background: isComparingOriginal ? '#2563eb' : '#ffffff', color: isComparingOriginal ? '#ffffff' : '#334155' }}
                  onMouseDown={() => setIsComparingOriginal(true)}
                  onMouseUp={() => setIsComparingOriginal(false)}
                  onMouseLeave={() => setIsComparingOriginal(false)}
                >
                  <Eye size={13} />
                  <span>Hold: View Original</span>
                </button>
              </div>

              {/* Standard Calibration Box */}
              <div className="card-clean" style={{ padding: 14, marginTop: 'auto', background: '#f8fafc' }}>
                <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', marginBottom: 6 }}>
                  Standard Calibration
                </div>
                <div style={{ fontSize: '0.72rem', color: '#475569', lineHeight: 1.6, fontFamily: 'var(--font-mono)' }}>
                  <div>Target: <strong style={{ color: '#0284c7' }}>180 × 180 px</strong></div>
                  <div>Guide: <strong style={{ color: '#0369a1' }}>35% Eye Line</strong></div>
                  <div>Guide: <strong style={{ color: '#b45309' }}>85% Chin Line</strong></div>
                  <div>Format: <strong style={{ color: '#059669' }}>PNG (RGBA)</strong></div>
                </div>
              </div>
            </div>

            {/* Center Stage & HUD Viewport */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: '#f8fafc', position: 'relative', overflow: 'hidden' }}>
              {/* Viewport Frame */}
              <div className="stage-wrapper">
                <div
                  ref={viewportRef}
                  className={`hud-viewport-clean ${
                    canvasBg === 'checker' ? 'bg-checkerboard-light' :
                    canvasBg === 'white' ? 'bg-stage-white' :
                    canvasBg === 'dark' ? 'bg-stage-dark' : 'bg-stage-navy'
                  } ${toolMode !== 'frame' ? 'brush-mode' : ''}`}
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
                  <div className="hud-overlay">
                    <div className="guide-line-eye">
                      <span>35% Eye Line</span>
                    </div>
                    <div className="guide-line-chin">
                      <span>85% Chin Line</span>
                    </div>
                    <div className="guide-cross-v" />
                    <div className="guide-cross-h" />
                  </div>

                  {/* Brush Indicator */}
                  <div
                    ref={brushCursorRef}
                    className={`brush-cursor-indicator-clean ${toolMode}`}
                  />
                </div>
              </div>

              {/* Coordinates Hint */}
              <div style={{ marginTop: 14, fontSize: '0.75rem', color: '#64748b', display: 'flex', alignItems: 'center', gap: 10 }}>
                <span>Drag to position &bull; Wheel to zoom</span>
                <span>&bull;</span>
                <span style={{ fontFamily: 'var(--font-mono)', color: '#0284c7', fontWeight: 600 }}>
                  {photos[currentIndex] && photoDataMap[photos[currentIndex]]
                    ? `x: ${Math.round(photoDataMap[photos[currentIndex]].offset_x)}px, y: ${Math.round(photoDataMap[photos[currentIndex]].offset_y)}px`
                    : 'x: 0px, y: 0px'}
                </span>
              </div>
            </div>
          </div>

          {/* Bottom Filmstrip Carousel */}
          <div style={{ height: 126, borderTop: '1px solid var(--border-default)', background: '#ffffff', padding: '8px 20px', display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                  Team Roster Filmstrip
                </span>
                <span style={{ fontSize: '0.6875rem', padding: '1px 8px', borderRadius: 4, background: '#eff6ff', color: '#2563eb', fontWeight: 600 }}>
                  Photo {currentIndex + 1} of {photos.length}
                </span>
              </div>

              <div style={{ display: 'flex', gap: 6 }}>
                <button
                  className="btn-ui btn-secondary"
                  style={{ padding: '3px 8px' }}
                  onClick={() => selectPhotoByIndex((currentIndex - 1 + photos.length) % photos.length)}
                  title="Previous Photo (Left Arrow)"
                >
                  <ArrowLeft size={13} />
                </button>
                <button
                  className="btn-ui btn-secondary"
                  style={{ padding: '3px 8px' }}
                  onClick={() => selectPhotoByIndex((currentIndex + 1) % photos.length)}
                  title="Next Photo (Right Arrow)"
                >
                  <ArrowRight size={13} />
                </button>
              </div>
            </div>

            <div className="filmstrip-track">
              {photos.map((name, idx) => {
                const data = photoDataMap[name];
                return (
                  <div
                    key={idx}
                    className={`filmstrip-item-clean ${idx === currentIndex ? 'active' : ''}`}
                    onClick={() => selectPhotoByIndex(idx)}
                  >
                    {data?.saved && <div className="dot-indicator dot-saved-clean" title="Saved" />}
                    {data?.hasCutout && !data?.saved && <div className="dot-indicator dot-cutout-clean" title="AI Cutout" />}
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
      {/* MODAL: SUPERADMIN PLATFORM & FLEET ORGANIZATION HUB */}
      {/* ========================================================= */}
      {showPlatformDashboard && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.3)', backdropFilter: 'blur(8px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div className="card-clean" style={{ maxWidth: 980, width: '100%', padding: 28, maxHeight: '90vh', overflowY: 'auto' }}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ width: 40, height: 40, borderRadius: 10, background: 'linear-gradient(135deg, #0f172a, #1e293b)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 12px rgba(15,23,42,0.15)' }}>
                  <Shield size={20} color="#ffffff" />
                </div>
                <div>
                  <div style={{ fontSize: '1.25rem', fontWeight: 800, color: '#0f172a', letterSpacing: '-0.02em', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span>SUPERADMIN ORGANIZATION HUB</span>
                    <span style={{ fontSize: '0.6875rem', padding: '2px 8px', borderRadius: 'var(--radius-full)', background: '#eff6ff', color: '#2563eb', fontWeight: 700, textTransform: 'uppercase' }}>
                      Master Root
                    </span>
                  </div>
                  <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                    Tenant Provisioning, Quota Allocation, Plan Tiers & Anti-Idle Heartbeat
                  </div>
                </div>
              </div>
              <button className="btn-ui btn-secondary" style={{ padding: '5px 12px' }} onClick={() => setShowPlatformDashboard(false)}>Close</button>
            </div>

            {/* Top KPI Metrics Cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
              <div style={{ padding: 14, borderRadius: 10, background: '#f8fafc', border: '1px solid #e2e8f0' }}>
                <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Total Organizations</div>
                <div style={{ fontSize: '1.45rem', fontWeight: 800, color: '#0f172a', marginTop: 4 }}>
                  {adminCompaniesList.length}
                </div>
                <div style={{ fontSize: '0.7rem', color: '#64748b', marginTop: 2 }}>Partitioned SaaS Tenants</div>
              </div>
              <div style={{ padding: 14, borderRadius: 10, background: '#f8fafc', border: '1px solid #e2e8f0' }}>
                <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Allocated Capacity</div>
                <div style={{ fontSize: '1.45rem', fontWeight: 800, color: '#0284c7', marginTop: 4 }}>
                  {adminCompaniesList.reduce((acc, c) => acc + (c.max_seats || 0), 0)}
                </div>
                <div style={{ fontSize: '0.7rem', color: '#64748b', marginTop: 2 }}>Total User Seats Provisioned</div>
              </div>
              <div style={{ padding: 14, borderRadius: 10, background: '#f8fafc', border: '1px solid #e2e8f0' }}>
                <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Active Seated Users</div>
                <div style={{ fontSize: '1.45rem', fontWeight: 800, color: '#10b981', marginTop: 4 }}>
                  {adminCompaniesList.reduce((acc, c) => acc + (c.used_seats || 0), 0)}
                </div>
                <div style={{ fontSize: '0.7rem', color: '#64748b', marginTop: 2 }}>Active Member Accounts</div>
              </div>
              <div style={{ padding: 14, borderRadius: 10, background: '#f8fafc', border: '1px solid #e2e8f0' }}>
                <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>SuperAdmin Scope</div>
                <div style={{ fontSize: '1.15rem', fontWeight: 800, color: '#d97706', marginTop: 8 }}>
                  Root Operator
                </div>
                <div style={{ fontSize: '0.7rem', color: '#64748b', marginTop: 4 }}>Zero Company Seats Consumed</div>
              </div>
            </div>

            {/* Navigation Tabs */}
            <div style={{ display: 'flex', marginBottom: 20 }}>
              <div className="segmented-track" style={{ width: '100%' }}>
                <button
                  className={`segmented-btn ${superAdminTab === 'companies' ? 'active' : ''}`}
                  style={{ flex: 1, fontSize: '0.78125rem', padding: '7px 0' }}
                  onClick={() => setSuperAdminTab('companies')}
                >
                  <Building size={14} />
                  <span>Organizations ({adminCompaniesList.length})</span>
                </button>
                <button
                  className={`segmented-btn ${superAdminTab === 'create_comp' ? 'active' : ''}`}
                  style={{ flex: 1, fontSize: '0.78125rem', padding: '7px 0' }}
                  onClick={() => setSuperAdminTab('create_comp')}
                >
                  <Plus size={14} />
                  <span>Provision Organization</span>
                </button>
                <button
                  className={`segmented-btn ${superAdminTab === 'plans' ? 'active' : ''}`}
                  style={{ flex: 1, fontSize: '0.78125rem', padding: '7px 0' }}
                  onClick={() => setSuperAdminTab('plans')}
                >
                  <Sliders size={14} />
                  <span>Plans & Tiers ({adminPlansList.length})</span>
                </button>
                <button
                  className={`segmented-btn ${superAdminTab === 'members' ? 'active' : ''}`}
                  style={{ flex: 1, fontSize: '0.78125rem', padding: '7px 0' }}
                  onClick={() => setSuperAdminTab('members')}
                >
                  <Users size={14} />
                  <span>Team Members & Assignment ({adminUsersList.length})</span>
                </button>
                <button
                  className={`segmented-btn ${superAdminTab === 'keepalive' ? 'active' : ''}`}
                  style={{ flex: 1, fontSize: '0.78125rem', padding: '7px 0' }}
                  onClick={() => setSuperAdminTab('keepalive')}
                >
                  <Activity size={14} />
                  <span>Cloud Keep-Alive</span>
                </button>
              </div>
            </div>

            {/* TAB 1: ORGANIZATIONS DIRECTORY */}
            {superAdminTab === 'companies' && (
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                  <div style={{ position: 'relative', width: 320 }}>
                    <Search size={14} color="#94a3b8" style={{ position: 'absolute', left: 12, top: 13 }} />
                    <input
                      type="text"
                      className="input-ui"
                      style={{ paddingLeft: 34, height: 38 }}
                      placeholder="Search organization or slug..."
                      value={adminCompanySearch}
                      onChange={e => setAdminCompanySearch(e.target.value)}
                    />
                  </div>
                  <button
                    className="btn-ui btn-primary"
                    style={{ fontSize: '0.78125rem', height: 38 }}
                    onClick={() => setSuperAdminTab('create_comp')}
                  >
                    <Plus size={14} />
                    <span>Provision Organization</span>
                  </button>
                </div>

                <div style={{ border: '1px solid var(--border-default)', borderRadius: 10, overflow: 'hidden' }}>
                  <table className="table-clean">
                    <thead>
                      <tr>
                        <th>Organization / Slug</th>
                        <th style={{ width: 130 }}>Plan Tier</th>
                        <th style={{ width: 220 }}>Seat Allocation & Quota</th>
                        <th style={{ width: 90 }}>Status</th>
                        <th style={{ width: 200, textAlign: 'right' }}>Actions & Assignment</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredAdminCompanies.length > 0 ? (
                        filteredAdminCompanies.map((c) => {
                          const used = c.used_seats || 0;
                          const max = c.max_seats || 10;
                          const pct = Math.min(100, Math.round((used / max) * 100));

                          return (
                            <tr key={c.id}>
                              <td>
                                <div style={{ fontWeight: 800, fontSize: '0.875rem', color: '#0f172a', display: 'flex', alignItems: 'center', gap: 10 }}>
                                  <div style={{ width: 32, height: 32, borderRadius: 8, background: '#eff6ff', border: '1px solid #bfdbfe', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: '0.75rem', color: '#2563eb' }}>
                                    {(c.name || 'CO').slice(0, 2).toUpperCase()}
                                  </div>
                                  <div>
                                    <div>{c.name}</div>
                                    <div style={{ fontSize: '0.72rem', color: '#64748b', fontFamily: 'var(--font-mono)' }}>slug: {c.slug}</div>
                                  </div>
                                </div>
                              </td>
                              <td>
                                <span style={{ fontSize: '0.72rem', fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: '#eff6ff', color: '#2563eb', border: '1px solid #bfdbfe', textTransform: 'uppercase' }}>
                                  {c.plan}
                                </span>
                              </td>
                              <td>
                                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', fontWeight: 600, color: '#334155', marginBottom: 4 }}>
                                  <span>{used} Seated Users</span>
                                  <span style={{ color: '#64748b' }}>{max} Seats Max</span>
                                </div>
                                <div style={{ height: 6, background: '#e2e8f0', borderRadius: 3, overflow: 'hidden' }}>
                                  <div style={{ width: `${pct}%`, height: '100%', background: 'linear-gradient(90deg, #2563eb, #3b82f6)', borderRadius: 3 }} />
                                </div>
                              </td>
                              <td>
                                <span style={{ fontSize: '0.6875rem', fontWeight: 700, padding: '2px 6px', borderRadius: 4, background: c.status === 'active' ? '#ecfdf5' : '#fef2f2', color: c.status === 'active' ? '#059669' : '#dc2626', border: `1px solid ${c.status === 'active' ? '#a7f3d0' : '#fecaca'}`, textTransform: 'uppercase' }}>
                                  {c.status}
                                </span>
                              </td>
                              <td style={{ textAlign: 'right' }}>
                                <div style={{ display: 'inline-flex', gap: 6 }}>
                                  <button
                                    className="btn-ui btn-secondary"
                                    style={{ fontSize: '0.72rem', padding: '4px 8px' }}
                                    onClick={() => {
                                      setQuotaTargetComp(c);
                                      setQuotaEditPlan(c.plan || 'team');
                                      setQuotaEditSeats(c.max_seats || 15);
                                    }}
                                    title="Assign Tier & Seats"
                                  >
                                    <Zap size={12} color="#2563eb" />
                                    <span>Quota</span>
                                  </button>
                                  <button
                                    className="btn-ui btn-secondary"
                                    style={{ fontSize: '0.72rem', padding: '4px 8px', color: '#0284c7', borderColor: '#bae6fd' }}
                                    onClick={() => {
                                      setAdminMemberFilterCompId(c.id);
                                      setSuperAdminTab('members');
                                    }}
                                    title="Inspect Members"
                                  >
                                    <Users size={12} />
                                    <span>Members ({used})</span>
                                  </button>
                                  <button
                                    className="btn-ui btn-danger"
                                    style={{ fontSize: '0.72rem', padding: '4px 6px' }}
                                    onClick={() => handleDeleteCompany(c.id, c.name)}
                                    title="Delete Company"
                                  >
                                    <Trash2 size={12} />
                                  </button>
                                </div>
                              </td>
                            </tr>
                          );
                        })
                      ) : (
                        <tr>
                          <td colSpan={5} style={{ textAlign: 'center', padding: 24, color: '#94a3b8' }}>
                            No organizations found matching search criteria.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* TAB 2: PROVISION NEW ORGANIZATION */}
            {superAdminTab === 'create_comp' && (
              <div style={{ background: '#ffffff', border: '1px solid var(--border-default)', borderRadius: 12, padding: 24 }}>
                <div style={{ fontSize: '1rem', fontWeight: 800, color: '#0f172a', marginBottom: 4 }}>
                  Provision New Tenant Organization
                </div>
                <div style={{ fontSize: '0.8125rem', color: '#64748b', marginBottom: 20 }}>
                  Create a dedicated company partition with custom plan quota and send an activation invitation to the lead administrator.
                </div>

                <form onSubmit={handleCreateCompanySubmit}>
                  <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: 14, marginBottom: 16 }}>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>Company / Organization Name *</label>
                      <input
                        type="text"
                        className="input-ui"
                        placeholder="e.g. Manchester Storm Media"
                        value={newCompName}
                        onChange={e => setNewCompName(e.target.value)}
                        required
                      />
                    </div>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>Subscription Plan *</label>
                      <select
                        className="input-ui"
                        value={newCompPlan}
                        onChange={e => {
                          const pSlug = e.target.value;
                          setNewCompPlan(pSlug);
                          const matchingPlan = adminPlansList.find(p => p.slug === pSlug);
                          if (matchingPlan) {
                            setNewCompSeats(matchingPlan.default_max_seats);
                          }
                        }}
                      >
                        {adminPlansList.map(p => (
                          <option key={p.id} value={p.slug}>
                            {p.name} ({p.default_max_seats} seats)
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>Max Seats Quota *</label>
                      <input
                        type="number"
                        min="1"
                        max="50000"
                        className="input-ui"
                        value={newCompSeats}
                        onChange={e => setNewCompSeats(parseInt(e.target.value) || 1)}
                        required
                      />
                    </div>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 20 }}>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>Lead Administrator Email (Optional)</label>
                      <input
                        type="email"
                        className="input-ui"
                        placeholder="lead.admin@organization.com"
                        value={newCompAdminEmail}
                        onChange={e => setNewCompAdminEmail(e.target.value)}
                      />
                    </div>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>Lead Administrator Full Name (Optional)</label>
                      <input
                        type="text"
                        className="input-ui"
                        placeholder="e.g. Liam Gallagher"
                        value={newCompAdminName}
                        onChange={e => setNewCompAdminName(e.target.value)}
                      />
                    </div>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
                    <button
                      type="button"
                      className="btn-ui btn-secondary"
                      onClick={() => setSuperAdminTab('companies')}
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={newCompSubmitting}
                      className="btn-ui btn-primary"
                      style={{ padding: '0 24px', height: 40 }}
                    >
                      <Plus size={15} />
                      <span>{newCompSubmitting ? 'Provisioning...' : 'Provision Organization & Activate Quota'}</span>
                    </button>
                  </div>
                </form>

                {newCompActivationLink && (
                  <div style={{ marginTop: 20, padding: 14, borderRadius: 8, background: '#f0fdf4', border: '1px solid #bbf7d0' }}>
                    <div style={{ fontSize: '0.78125rem', fontWeight: 700, color: '#15803d', marginBottom: 4 }}>
                      Lead Administrator Activation Link:
                    </div>
                    <div style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: '#166534', wordBreak: 'break-all' }}>
                      {newCompActivationLink}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* TAB 3: PLANS & TIERS MANAGEMENT */}
            {superAdminTab === 'plans' && (
              <div>
                <div style={{ padding: 12, borderRadius: 8, background: '#eff6ff', border: '1px solid #bfdbfe', marginBottom: 18, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ fontSize: '0.78125rem', color: '#1d4ed8' }}>
                    <strong>SuperUser Plan Customizer:</strong> You can add and edit plan tiers here in real-time, or manage them directly in the backend Django Admin at <a href="http://localhost:8000/admin/accounts/plan/" target="_blank" rel="noreferrer" style={{ textDecoration: 'underline', fontWeight: 700 }}>/admin/accounts/plan/</a>.
                  </div>
                  <a
                    href="http://localhost:8000/admin/accounts/plan/"
                    target="_blank"
                    rel="noreferrer"
                    className="btn-ui btn-secondary"
                    style={{ fontSize: '0.72rem', padding: '4px 10px', background: '#ffffff' }}
                  >
                    <ExternalLink size={12} />
                    <span>Open Django Admin</span>
                  </a>
                </div>

                {/* Plan Form */}
                <div style={{ background: '#ffffff', border: '1px solid var(--border-default)', borderRadius: 12, padding: 20, marginBottom: 20 }}>
                  <div style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#0f172a', marginBottom: 12 }}>
                    {editingPlan ? `Edit Plan Tier: ${editingPlan.name}` : 'Add New Plan Tier'}
                  </div>

                  <form onSubmit={handleSavePlanSubmit}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr 1fr 1fr', gap: 12, marginBottom: 12 }}>
                      <div>
                        <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 4 }}>Plan Name *</label>
                        <input
                          type="text"
                          className="input-ui"
                          placeholder="e.g. Pro League Pass"
                          value={planFormName}
                          onChange={e => {
                            setPlanFormName(e.target.value);
                            if (!editingPlan) {
                              setPlanFormSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, ''));
                            }
                          }}
                          required
                        />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 4 }}>Slug *</label>
                        <input
                          type="text"
                          className="input-ui"
                          placeholder="pro-league"
                          value={planFormSlug}
                          onChange={e => setPlanFormSlug(e.target.value)}
                          disabled={Boolean(editingPlan)}
                          required
                        />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 4 }}>Default Seats *</label>
                        <input
                          type="number"
                          min="1"
                          max="50000"
                          className="input-ui"
                          value={planFormSeats}
                          onChange={e => setPlanFormSeats(parseInt(e.target.value) || 1)}
                          required
                        />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 4 }}>Price Note</label>
                        <input
                          type="text"
                          className="input-ui"
                          placeholder="$99/mo"
                          value={planFormPrice}
                          onChange={e => setPlanFormPrice(e.target.value)}
                        />
                      </div>
                    </div>

                    <div style={{ marginBottom: 16 }}>
                      <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 4 }}>Plan Description & Feature Highlights</label>
                      <input
                        type="text"
                        className="input-ui"
                        placeholder="Comprehensive multi-team headshot studio with unlimited U-2-Net cutout inference"
                        value={planFormDesc}
                        onChange={e => setPlanFormDesc(e.target.value)}
                      />
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
                      {editingPlan && (
                        <button
                          type="button"
                          className="btn-ui btn-secondary"
                          onClick={() => {
                            setEditingPlan(null);
                            setPlanFormName('');
                            setPlanFormSlug('');
                            setPlanFormSeats(10);
                            setPlanFormPrice('$29/mo');
                            setPlanFormDesc('');
                          }}
                        >
                          Cancel Edit
                        </button>
                      )}
                      <button
                        type="submit"
                        disabled={planFormSubmitting}
                        className="btn-ui btn-primary"
                        style={{ padding: '0 20px', height: 38 }}
                      >
                        <Save size={14} />
                        <span>{editingPlan ? 'Update Plan Tier' : 'Save New Plan'}</span>
                      </button>
                    </div>
                  </form>
                </div>

                {/* Plans Table */}
                <div style={{ border: '1px solid var(--border-default)', borderRadius: 10, overflow: 'hidden' }}>
                  <table className="table-clean">
                    <thead>
                      <tr>
                        <th>Plan Name & Slug</th>
                        <th style={{ width: 120 }}>Default Seats</th>
                        <th style={{ width: 110 }}>Price</th>
                        <th>Description</th>
                        <th style={{ width: 120, textAlign: 'right' }}>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {adminPlansList.map(plan => (
                        <tr key={plan.id}>
                          <td>
                            <div style={{ fontWeight: 700, color: '#0f172a' }}>{plan.name}</div>
                            <div style={{ fontSize: '0.72rem', color: '#64748b', fontFamily: 'var(--font-mono)' }}>slug: {plan.slug}</div>
                          </td>
                          <td style={{ fontWeight: 700, color: '#0284c7' }}>
                            {plan.default_max_seats} Seats
                          </td>
                          <td style={{ fontWeight: 600, color: '#10b981' }}>
                            {plan.price_monthly}
                          </td>
                          <td style={{ fontSize: '0.75rem', color: '#475569' }}>
                            {plan.description || 'Standard plan tier'}
                          </td>
                          <td style={{ textAlign: 'right' }}>
                            <div style={{ display: 'inline-flex', gap: 6 }}>
                              <button
                                className="btn-ui btn-secondary"
                                style={{ padding: '4px 8px', fontSize: '0.72rem' }}
                                onClick={() => {
                                  setEditingPlan(plan);
                                  setPlanFormName(plan.name);
                                  setPlanFormSlug(plan.slug);
                                  setPlanFormSeats(plan.default_max_seats);
                                  setPlanFormPrice(plan.price_monthly);
                                  setPlanFormDesc(plan.description);
                                }}
                                title="Edit Plan"
                              >
                                <Edit2 size={12} />
                              </button>
                              <button
                                className="btn-ui btn-danger"
                                style={{ padding: '4px 8px', fontSize: '0.72rem' }}
                                onClick={() => handleDeletePlan(plan.id, plan.name)}
                                title="Delete Plan"
                              >
                                <Trash2 size={12} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* TAB 4: TEAM MEMBERS & ASSIGNMENT */}
            {superAdminTab === 'members' && (
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14, gap: 12 }}>
                  <div style={{ display: 'flex', gap: 12, flex: 1 }}>
                    <div style={{ width: 220 }}>
                      <select
                        className="input-ui"
                        style={{ height: 38 }}
                        value={adminMemberFilterCompId}
                        onChange={e => setAdminMemberFilterCompId(e.target.value)}
                      >
                        <option value="all">All Organizations ({adminUsersList.length})</option>
                        <option value="unassigned">Unassigned Users</option>
                        {adminCompaniesList.map(c => (
                          <option key={c.id} value={c.id}>
                            {c.name}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div style={{ position: 'relative', flex: 1, maxWidth: 300 }}>
                      <Search size={14} color="#94a3b8" style={{ position: 'absolute', left: 12, top: 13 }} />
                      <input
                        type="text"
                        className="input-ui"
                        style={{ paddingLeft: 34, height: 38 }}
                        placeholder="Search user by name or email..."
                        value={adminMemberSearch}
                        onChange={e => setAdminMemberSearch(e.target.value)}
                      />
                    </div>
                  </div>
                </div>

                <div style={{ border: '1px solid var(--border-default)', borderRadius: 10, overflow: 'hidden' }}>
                  <table className="table-clean">
                    <thead>
                      <tr>
                        <th>User Profile</th>
                        <th>Assigned Organization</th>
                        <th style={{ width: 130 }}>Role</th>
                        <th style={{ width: 180, textAlign: 'right' }}>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredAdminUsers.length > 0 ? (
                        filteredAdminUsers.map(u => (
                          <tr key={u.id}>
                            <td>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                <div style={{ width: 30, height: 30, borderRadius: '50%', background: '#eff6ff', border: '1px solid #bfdbfe', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75rem', fontWeight: 700, color: '#2563eb' }}>
                                  {(u.full_name || u.email).slice(0, 2).toUpperCase()}
                                </div>
                                <div>
                                  <div style={{ fontWeight: 700, color: '#0f172a' }}>{u.full_name}</div>
                                  <div style={{ fontSize: '0.72rem', color: '#64748b' }}>{u.email}</div>
                                </div>
                              </div>
                            </td>
                            <td>
                              <span style={{ fontWeight: 600, color: u.company_id ? '#0f172a' : '#94a3b8' }}>
                                {u.company_name}
                              </span>
                            </td>
                            <td>
                              <span style={{ fontSize: '0.6875rem', fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: u.is_superadmin ? '#f5f3ff' : (u.role === 'company_admin' ? '#eff6ff' : '#f8fafc'), color: u.is_superadmin ? '#7c3aed' : (u.role === 'company_admin' ? '#2563eb' : '#475569'), border: `1px solid ${u.is_superadmin ? '#ddd6fe' : (u.role === 'company_admin' ? '#bfdbfe' : '#e2e8f0')}`, textTransform: 'uppercase' }}>
                                {u.is_superadmin ? 'SuperAdmin' : (u.role === 'company_admin' ? 'Company Admin' : 'Member')}
                              </span>
                            </td>
                            <td style={{ textAlign: 'right' }}>
                              <div style={{ display: 'inline-flex', gap: 6 }}>
                                <button
                                  className="btn-ui btn-secondary"
                                  style={{ padding: '4px 8px', fontSize: '0.72rem' }}
                                  onClick={() => {
                                    setAssignTargetUser(u);
                                    setAssignTargetCompId(u.company_id || '');
                                    setAssignTargetRole(u.role || 'member');
                                  }}
                                  title="Assign Organization & Role"
                                >
                                  <UserPlus size={12} color="#2563eb" />
                                  <span>Assign Team</span>
                                </button>
                                {u.company_id && (
                                  <button
                                    className="btn-ui btn-danger"
                                    style={{ padding: '4px 8px', fontSize: '0.72rem' }}
                                    onClick={() => handleRemoveUserFromCompany(u.id, u.email)}
                                    title="Remove from Company"
                                  >
                                    <span>Remove</span>
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={4} style={{ textAlign: 'center', padding: 24, color: '#94a3b8' }}>
                            No users found.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* TAB 5: CLOUD KEEP-ALIVE & ANTI-IDLE */}
            {superAdminTab === 'keepalive' && (
              <div style={{ background: '#ffffff', border: '1px solid var(--border-default)', borderRadius: 12, padding: 24 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
                  <div>
                    <div style={{ fontSize: '1rem', fontWeight: 800, color: '#0f172a', display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span>Cloud Keep-Alive & Anti-Idle Heartbeat</span>
                      <span style={{ fontSize: '0.6875rem', padding: '2px 8px', borderRadius: 4, background: '#eff6ff', color: '#2563eb', fontWeight: 700 }}>Active</span>
                    </div>
                    <div style={{ fontSize: '0.78125rem', color: '#64748b', marginTop: 4 }}>
                      Sends lightweight health pings to keep cloud services warm and prevent inactivity sleep.
                    </div>
                  </div>
                  <button
                    className="btn-ui btn-primary"
                    style={{ height: 38 }}
                    onClick={handleTestPingNow}
                    disabled={pingLoading}
                  >
                    <Activity size={14} />
                    <span>{pingLoading ? 'Pinging...' : 'Test Ping Now'}</span>
                  </button>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
                  <div style={{ padding: 14, borderRadius: 10, background: '#f8fafc', border: '1px solid #e2e8f0' }}>
                    <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Ping Interval</div>
                    <div style={{ fontSize: '1.25rem', fontWeight: 800, color: '#0f172a', marginTop: 4 }}>10 min (600s)</div>
                    <div style={{ fontSize: '0.7rem', color: '#64748b', marginTop: 2 }}>Safe idle threshold buffer</div>
                  </div>
                  <div style={{ padding: 14, borderRadius: 10, background: '#f8fafc', border: '1px solid #e2e8f0' }}>
                    <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Total Heartbeats</div>
                    <div style={{ fontSize: '1.25rem', fontWeight: 800, color: '#10b981', marginTop: 4 }}>
                      {keepAliveData?.successful_pings || 1} pings
                    </div>
                    <div style={{ fontSize: '0.7rem', color: '#64748b', marginTop: 2 }}>Outbound-to-edge roundtrips</div>
                  </div>
                  <div style={{ padding: 14, borderRadius: 10, background: '#f8fafc', border: '1px solid #e2e8f0' }}>
                    <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Roundtrip Latency</div>
                    <div style={{ fontSize: '1.25rem', fontWeight: 800, color: '#2563eb', marginTop: 4 }}>
                      {keepAliveData?.last_ping_latency_ms || 12} ms
                    </div>
                    <div style={{ fontSize: '0.7rem', color: '#64748b', marginTop: 2 }}>Edge proxy response time</div>
                  </div>
                  <div style={{ padding: 14, borderRadius: 10, background: '#f8fafc', border: '1px solid #e2e8f0' }}>
                    <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase' }}>Status</div>
                    <div style={{ fontSize: '1.25rem', fontWeight: 800, color: '#10b981', marginTop: 4 }}>OK (Warm)</div>
                    <div style={{ fontSize: '0.7rem', color: '#64748b', marginTop: 2 }}>Server responding normally</div>
                  </div>
                </div>

                <div style={{ padding: 14, borderRadius: 8, background: '#f8fafc', border: '1px solid #e2e8f0' }}>
                  <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#475569', marginBottom: 4 }}>Current Edge Health Target:</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78125rem', color: '#0284c7' }}>
                    {keepAliveData?.target_url || `${window.location.origin}/healthz`}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* DIALOG: ASSIGN COMPANY QUOTA */}
      {/* ========================================================= */}
      {quotaTargetComp && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.4)', backdropFilter: 'blur(4px)', zIndex: 1100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
          <div className="card-clean" style={{ maxWidth: 440, width: '100%', padding: 24 }}>
            <div style={{ fontSize: '1.05rem', fontWeight: 800, color: '#0f172a', marginBottom: 4 }}>
              Assign Quota & Plan: {quotaTargetComp.name}
            </div>
            <div style={{ fontSize: '0.75rem', color: '#64748b', marginBottom: 16 }}>
              Update the subscription plan tier and maximum seat capacity for this tenant.
            </div>

            <form onSubmit={handleUpdateCompanyQuota}>
              <div style={{ marginBottom: 14 }}>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>Select Subscription Plan</label>
                <select
                  className="input-ui"
                  value={quotaEditPlan}
                  onChange={e => {
                    const pSlug = e.target.value;
                    setQuotaEditPlan(pSlug);
                    const matchingPlan = adminPlansList.find(p => p.slug === pSlug);
                    if (matchingPlan) {
                      setQuotaEditSeats(matchingPlan.default_max_seats);
                    }
                  }}
                >
                  {adminPlansList.map(p => (
                    <option key={p.id} value={p.slug}>
                      {p.name} ({p.default_max_seats} seats)
                    </option>
                  ))}
                </select>
              </div>

              <div style={{ marginBottom: 20 }}>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>Maximum Seats Quota</label>
                <input
                  type="number"
                  min="1"
                  max="50000"
                  className="input-ui"
                  value={quotaEditSeats}
                  onChange={e => setQuotaEditSeats(parseInt(e.target.value) || 1)}
                  required
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
                <button
                  type="button"
                  className="btn-ui btn-secondary"
                  onClick={() => setQuotaTargetComp(null)}
                >
                  Cancel
                </button>
                <button type="submit" className="btn-ui btn-primary">
                  Save Quota
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* DIALOG: ASSIGN USER TO ORGANIZATION & ROLE */}
      {/* ========================================================= */}
      {assignTargetUser && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.4)', backdropFilter: 'blur(4px)', zIndex: 1100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
          <div className="card-clean" style={{ maxWidth: 460, width: '100%', padding: 24 }}>
            <div style={{ fontSize: '1.05rem', fontWeight: 800, color: '#0f172a', marginBottom: 4 }}>
              Assign Organization: {assignTargetUser.full_name}
            </div>
            <div style={{ fontSize: '0.75rem', color: '#64748b', marginBottom: 16 }}>
              Select tenant organization and user permission scope for {assignTargetUser.email}.
            </div>

            <form onSubmit={handleAssignUserCompanySubmit}>
              <div style={{ marginBottom: 14 }}>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>Target Organization</label>
                <select
                  className="input-ui"
                  value={assignTargetCompId}
                  onChange={e => setAssignTargetCompId(e.target.value)}
                >
                  <option value="">Unassigned (No Organization)</option>
                  {adminCompaniesList.map(c => (
                    <option key={c.id} value={c.id}>
                      {c.name} ({c.plan.toUpperCase()})
                    </option>
                  ))}
                </select>
              </div>

              <div style={{ marginBottom: 20 }}>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>Role & Permissions</label>
                <select
                  className="input-ui"
                  value={assignTargetRole}
                  onChange={e => setAssignTargetRole(e.target.value)}
                >
                  <option value="member">Standard Member (Editor)</option>
                  <option value="company_admin">Company Admin (Team Manager)</option>
                  <option value="superadmin">SuperAdmin (Master Root)</option>
                </select>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
                <button
                  type="button"
                  className="btn-ui btn-secondary"
                  onClick={() => setAssignTargetUser(null)}
                >
                  Cancel
                </button>
                <button type="submit" className="btn-ui btn-primary">
                  Save Assignment
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* MODAL: ORGANIZATION & TEAM MANAGEMENT HUB (RBAC) */}
      {/* ========================================================= */}
      {showOrgHub && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.35)', backdropFilter: 'blur(8px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
          <div className="card-clean" style={{ maxWidth: 760, width: '100%', maxHeight: '88vh', display: 'flex', flexDirection: 'column', padding: 0, overflow: 'hidden' }}>
            {/* Modal Header */}
            <div style={{ padding: '20px 24px', borderBottom: '1px solid #e2e8f0', background: '#f8fafc', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ width: 38, height: 38, borderRadius: 10, background: '#ecfdf5', border: '1px solid #a7f3d0', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <Users size={20} color="#059669" />
                </div>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <h2 style={{ fontSize: '1.2rem', fontWeight: 800, color: '#0f172a' }}>
                      {user.company?.name || 'Organization'}
                    </h2>
                    <span style={{ fontSize: '0.6875rem', fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: '#eff6ff', color: '#1d4ed8', border: '1px solid #bfdbfe', textTransform: 'uppercase' }}>
                      {user.company?.plan || 'Free'} Tier
                    </span>
                  </div>
                  <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: 2 }}>
                    Team staff roster, role-based permissions, and seat allocation
                  </div>
                </div>
              </div>
              <button
                className="btn-ui btn-secondary"
                style={{ padding: '6px 12px', fontSize: '0.75rem' }}
                onClick={() => setShowOrgHub(false)}
              >
                Close
              </button>
            </div>

            {/* Quota Progress Banner */}
            <div style={{ padding: '16px 24px', background: '#ffffff', borderBottom: '1px solid #f1f5f9' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8, fontSize: '0.75rem' }}>
                <span style={{ fontWeight: 600, color: '#334155' }}>
                  Seat Capacity: <strong>{user.company?.used_seats || 0} Active</strong> &bull; <strong>{user.company?.pending_invitations || 0} Pending</strong> of <strong>{user.company?.max_seats || 0} Total</strong>
                </span>
                <span style={{ fontWeight: 700, color: (user.company?.remaining_seats || 0) > 0 ? '#16a34a' : '#dc2626' }}>
                  {(user.company?.remaining_seats || 0) > 0 ? `${user.company?.remaining_seats} Seats Available` : 'Capacity Reached'}
                </span>
              </div>
              <div style={{ width: '100%', height: 8, background: '#e2e8f0', borderRadius: 4, overflow: 'hidden' }}>
                <div
                  style={{
                    height: '100%',
                    width: `${Math.min(100, (((user.company?.used_seats || 0) + (user.company?.pending_invitations || 0)) / Math.max(1, (user.company?.max_seats || 1))) * 100)}%`,
                    background: ((user.company?.remaining_seats || 0) > 0) ? 'linear-gradient(90deg, #10b981, #059669)' : '#ef4444',
                    borderRadius: 4,
                    transition: 'width 0.3s ease'
                  }}
                />
              </div>
            </div>

            {/* Tabs Header */}
            <div style={{ display: 'flex', borderBottom: '1px solid #e2e8f0', background: '#f8fafc', padding: '0 24px' }}>
              <button
                style={{
                  padding: '12px 16px',
                  fontSize: '0.8125rem',
                  fontWeight: orgHubTab === 'members' ? 700 : 500,
                  color: orgHubTab === 'members' ? '#2563eb' : '#64748b',
                  borderBottom: orgHubTab === 'members' ? '2px solid #2563eb' : '2px solid transparent',
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer'
                }}
                onClick={() => setOrgHubTab('members')}
              >
                Team Members ({orgMembers.length})
              </button>
              <button
                style={{
                  padding: '12px 16px',
                  fontSize: '0.8125rem',
                  fontWeight: orgHubTab === 'invitations' ? 700 : 500,
                  color: orgHubTab === 'invitations' ? '#2563eb' : '#64748b',
                  borderBottom: orgHubTab === 'invitations' ? '2px solid #2563eb' : '2px solid transparent',
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer'
                }}
                onClick={() => setOrgHubTab('invitations')}
              >
                Pending Invitations ({orgInvitations.length})
              </button>
              <button
                style={{
                  padding: '12px 16px',
                  fontSize: '0.8125rem',
                  fontWeight: orgHubTab === 'invite' ? 700 : 500,
                  color: orgHubTab === 'invite' ? '#2563eb' : '#64748b',
                  borderBottom: orgHubTab === 'invite' ? '2px solid #2563eb' : '2px solid transparent',
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer'
                }}
                onClick={() => setOrgHubTab('invite')}
              >
                ➕ Invite Staff Member
              </button>
            </div>

            {/* Modal Body */}
            <div style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
              {orgDataLoading ? (
                <div style={{ display: 'flex', justifyContent: 'center', padding: '40px 0' }}>
                  <RefreshCw className="animate-spin" size={24} color="#64748b" />
                </div>
              ) : (
                <>
                  {/* TAB 1: MEMBERS */}
                  {orgHubTab === 'members' && (
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                        <div style={{ position: 'relative', width: 280 }}>
                          <Search size={14} color="#94a3b8" style={{ position: 'absolute', left: 10, top: 10 }} />
                          <input
                            type="text"
                            className="input-ui"
                            style={{ paddingLeft: 30, fontSize: '0.75rem', height: 34 }}
                            placeholder="Filter members by name or email..."
                            value={orgMemberSearch}
                            onChange={e => setOrgMemberSearch(e.target.value)}
                          />
                        </div>
                        <button
                          className="btn-ui btn-primary"
                          style={{ fontSize: '0.75rem', padding: '6px 14px' }}
                          onClick={() => setOrgHubTab('invite')}
                        >
                          <Plus size={14} />
                          <span>Invite Member</span>
                        </button>
                      </div>

                      <div style={{ border: '1px solid #e2e8f0', borderRadius: 8, overflow: 'hidden' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78125rem' }}>
                          <thead>
                            <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0', textAlign: 'left', color: '#64748b' }}>
                              <th style={{ padding: '10px 14px', fontWeight: 600 }}>Member</th>
                              <th style={{ padding: '10px 14px', fontWeight: 600 }}>Role</th>
                              <th style={{ padding: '10px 14px', fontWeight: 600 }}>Joined</th>
                              <th style={{ padding: '10px 14px', fontWeight: 600, textAlign: 'right' }}>Actions</th>
                            </tr>
                          </thead>
                          <tbody>
                            {orgMembers
                              .filter(m => !orgMemberSearch || m.full_name.toLowerCase().includes(orgMemberSearch.toLowerCase()) || m.email.toLowerCase().includes(orgMemberSearch.toLowerCase()))
                              .map(m => (
                                <tr key={m.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                                  <td style={{ padding: '10px 14px' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                      <div style={{ width: 30, height: 30, borderRadius: '50%', background: m.is_self ? '#eff6ff' : '#f1f5f9', border: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75rem', fontWeight: 700, color: m.is_self ? '#2563eb' : '#475569' }}>
                                        {m.full_name ? m.full_name.slice(0, 2).toUpperCase() : m.email.slice(0, 2).toUpperCase()}
                                      </div>
                                      <div>
                                        <div style={{ fontWeight: 600, color: '#0f172a' }}>
                                          {m.full_name} {m.is_self && <span style={{ fontSize: '0.6875rem', color: '#2563eb', fontWeight: 700 }}>(You)</span>}
                                        </div>
                                        <div style={{ fontSize: '0.71875rem', color: '#64748b' }}>{m.email}</div>
                                      </div>
                                    </div>
                                  </td>
                                  <td style={{ padding: '10px 14px' }}>
                                    {m.role === 'superadmin' ? (
                                      <span style={{ fontSize: '0.6875rem', fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: '#f5f3ff', color: '#7c3aed', border: '1px solid #ddd6fe' }}>
                                        SuperAdmin
                                      </span>
                                    ) : m.role === 'company_admin' ? (
                                      <span style={{ fontSize: '0.6875rem', fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: '#ecfdf5', color: '#059669', border: '1px solid #a7f3d0' }}>
                                        Org Admin
                                      </span>
                                    ) : (
                                      <span style={{ fontSize: '0.6875rem', fontWeight: 600, padding: '2px 8px', borderRadius: 4, background: '#f1f5f9', color: '#475569', border: '1px solid #e2e8f0' }}>
                                        Team Member
                                      </span>
                                    )}
                                  </td>
                                  <td style={{ padding: '10px 14px', color: '#64748b', fontSize: '0.72rem' }}>
                                    {new Date(m.date_joined).toLocaleDateString()}
                                  </td>
                                  <td style={{ padding: '10px 14px', textAlign: 'right' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 6 }}>
                                      {!m.is_self && !m.is_superadmin && (
                                        <>
                                          {m.role === 'member' ? (
                                            <button
                                              className="btn-ui btn-secondary"
                                              style={{ fontSize: '0.6875rem', padding: '4px 8px' }}
                                              disabled={orgActionLoading}
                                              onClick={() => handleUpdateMemberRole(m.id, 'company_admin')}
                                              title="Promote to Organization Administrator"
                                            >
                                              Promote Admin
                                            </button>
                                          ) : (
                                            <button
                                              className="btn-ui btn-secondary"
                                              style={{ fontSize: '0.6875rem', padding: '4px 8px' }}
                                              disabled={orgActionLoading}
                                              onClick={() => handleUpdateMemberRole(m.id, 'member')}
                                              title="Demote to Standard Member"
                                            >
                                              Set Member
                                            </button>
                                          )}
                                          <button
                                            className="btn-ui btn-ghost"
                                            style={{ color: '#ef4444', padding: '4px 6px' }}
                                            disabled={orgActionLoading}
                                            onClick={() => handleRemoveMember(m.id, m.email)}
                                            title="Remove member and release seat"
                                          >
                                            <Trash2 size={14} />
                                          </button>
                                        </>
                                      )}
                                    </div>
                                  </td>
                                </tr>
                              ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {/* TAB 2: PENDING INVITATIONS */}
                  {orgHubTab === 'invitations' && (
                    <div>
                      {orgInvitations.length === 0 ? (
                        <div style={{ textAlign: 'center', padding: '36px 0', color: '#64748b' }}>
                          <Users size={32} color="#cbd5e1" style={{ margin: '0 auto 10px' }} />
                          <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#334155' }}>No active invitations</div>
                          <div style={{ fontSize: '0.75rem', marginTop: 4 }}>
                            All invited colleagues have accepted their seats or invitations expired.
                          </div>
                          <button
                            className="btn-ui btn-primary"
                            style={{ marginTop: 14, fontSize: '0.75rem', padding: '6px 14px' }}
                            onClick={() => setOrgHubTab('invite')}
                          >
                            Send New Invite
                          </button>
                        </div>
                      ) : (
                        <div style={{ border: '1px solid #e2e8f0', borderRadius: 8, overflow: 'hidden' }}>
                          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78125rem' }}>
                            <thead>
                              <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0', textAlign: 'left', color: '#64748b' }}>
                                <th style={{ padding: '10px 14px', fontWeight: 600 }}>Invited Colleague</th>
                                <th style={{ padding: '10px 14px', fontWeight: 600 }}>Target Role</th>
                                <th style={{ padding: '10px 14px', fontWeight: 600 }}>Status / Expiry</th>
                                <th style={{ padding: '10px 14px', fontWeight: 600, textAlign: 'right' }}>Actions</th>
                              </tr>
                            </thead>
                            <tbody>
                              {orgInvitations.map(inv => (
                                <tr key={inv.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                                  <td style={{ padding: '10px 14px' }}>
                                    <div style={{ fontWeight: 600, color: '#0f172a' }}>{inv.email}</div>
                                    <div style={{ fontSize: '0.71875rem', color: '#64748b' }}>
                                      {inv.full_name ? `Name: ${inv.full_name}` : 'Pending Name'} &bull; Invited by: {inv.invited_by || 'Admin'}
                                    </div>
                                  </td>
                                  <td style={{ padding: '10px 14px' }}>
                                    <span style={{ fontSize: '0.6875rem', fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: inv.role === 'company_admin' ? '#ecfdf5' : '#f1f5f9', color: inv.role === 'company_admin' ? '#059669' : '#475569' }}>
                                      {inv.role === 'company_admin' ? 'Org Admin' : 'Team Member'}
                                    </span>
                                  </td>
                                  <td style={{ padding: '10px 14px', fontSize: '0.72rem' }}>
                                    {inv.is_expired ? (
                                      <span style={{ color: '#ef4444', fontWeight: 600 }}>Expired</span>
                                    ) : (
                                      <span style={{ color: '#16a34a', fontWeight: 600 }}>
                                        Active &bull; {inv.expires_at ? new Date(inv.expires_at).toLocaleDateString() : '7 days'}
                                      </span>
                                    )}
                                  </td>
                                  <td style={{ padding: '10px 14px', textAlign: 'right' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 6 }}>
                                      <button
                                        className="btn-ui btn-secondary"
                                        style={{ fontSize: '0.6875rem', padding: '4px 8px' }}
                                        onClick={async () => {
                                          const link = window.location.origin + inv.activation_url;
                                          try {
                                            await navigator.clipboard.writeText(link);
                                            showToast('Activation link copied to clipboard!');
                                          } catch {
                                            showToast('Link: ' + link);
                                          }
                                        }}
                                        title="Copy one-click activation URL"
                                      >
                                        <Copy size={12} />
                                        <span>Copy Link</span>
                                      </button>
                                      <button
                                        className="btn-ui btn-secondary"
                                        style={{ fontSize: '0.6875rem', padding: '4px 8px' }}
                                        disabled={orgActionLoading}
                                        onClick={() => handleResendInvitation(inv.id)}
                                        title="Renew expiration by 7 days"
                                      >
                                        <RefreshCw size={12} />
                                        <span>Renew</span>
                                      </button>
                                      <button
                                        className="btn-ui btn-ghost"
                                        style={{ color: '#ef4444', padding: '4px 6px' }}
                                        disabled={orgActionLoading}
                                        onClick={() => handleRevokeInvitation(inv.id)}
                                        title="Revoke invitation and free seat"
                                      >
                                        <Trash2 size={13} />
                                      </button>
                                    </div>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  )}

                  {/* TAB 3: INVITE FORM */}
                  {orgHubTab === 'invite' && (
                    <div style={{ maxWidth: 500, margin: '0 auto' }}>
                      <div style={{ marginBottom: 18, textAlign: 'center' }}>
                        <div style={{ fontSize: '1.05rem', fontWeight: 800, color: '#0f172a' }}>
                          Invite Staff to {user.company?.name}
                        </div>
                        <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: 4 }}>
                          Invited staff receive a secure token to activate their account and set their password.
                        </div>
                      </div>

                      {/* Quota Check Alert */}
                      {(user.company?.remaining_seats || 0) <= 0 ? (
                        <div style={{ padding: 14, borderRadius: 8, background: '#fef2f2', border: '1px solid #fecaca', marginBottom: 18, color: '#991b1b', fontSize: '0.75rem' }}>
                          <strong>Seat Quota Exhausted:</strong> All {user.company?.max_seats} seats are currently assigned or reserved. Please revoke an unused invitation or upgrade your organization tier.
                        </div>
                      ) : (
                        <div style={{ padding: 12, borderRadius: 8, background: '#eff6ff', border: '1px solid #bfdbfe', marginBottom: 18, color: '#1e40af', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: 8 }}>
                          <Check size={16} color="#2563eb" />
                          <span>
                            <strong>{user.company?.remaining_seats} seats remaining.</strong> Inviting a colleague will reserve 1 seat until accepted or revoked.
                          </span>
                        </div>
                      )}

                      <form onSubmit={handleCreateOrgInvitation} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                        <div>
                          <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>
                            Colleague Work Email *
                          </label>
                          <input
                            type="email"
                            className="input-ui"
                            placeholder="photographer@school.edu"
                            value={inviteEmail}
                            onChange={e => setInviteEmail(e.target.value)}
                            required
                          />
                        </div>

                        <div>
                          <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>
                            Full Name (Optional)
                          </label>
                          <input
                            type="text"
                            className="input-ui"
                            placeholder="e.g. Jordan Miller"
                            value={inviteName}
                            onChange={e => setInviteName(e.target.value)}
                          />
                        </div>

                        <div>
                          <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>
                            Role & Permissions *
                          </label>
                          <select
                            className="input-ui"
                            value={inviteRole}
                            onChange={e => setInviteRole(e.target.value as 'member' | 'company_admin')}
                          >
                            <option value="member">Standard Member (Studio Photo Editor & Roster Ingestion)</option>
                            <option value="company_admin">Organization Administrator (Full Team & Seat Control)</option>
                          </select>
                        </div>

                        <button
                          type="submit"
                          className="btn-ui btn-primary"
                          style={{ height: 42, marginTop: 6 }}
                          disabled={orgActionLoading || (user.company?.remaining_seats || 0) <= 0}
                        >
                          {orgActionLoading ? <RefreshCw className="animate-spin" size={16} /> : <UserPlus size={16} />}
                          <span>Issue Invitation & Reserve Seat</span>
                        </button>
                      </form>

                      {inviteLink && (
                        <div style={{ marginTop: 20, padding: 14, borderRadius: 8, background: '#f0fdf4', border: '1px solid #bbf7d0' }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                            <span style={{ fontSize: '0.75rem', fontWeight: 700, color: '#166534' }}>Activation Link Ready</span>
                            <button
                              className="btn-ui btn-secondary"
                              style={{ fontSize: '0.6875rem', padding: '3px 8px' }}
                              onClick={async () => {
                                try {
                                  await navigator.clipboard.writeText(inviteLink);
                                  showToast('Link copied to clipboard!');
                                } catch {
                                  showToast('Link: ' + inviteLink);
                                }
                              }}
                            >
                              Copy Link
                            </button>
                          </div>
                          <div style={{ fontSize: '0.71875rem', fontFamily: 'var(--font-mono)', color: '#15803d', wordBreak: 'break-all' }}>
                            {inviteLink}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* MODAL: DEDICATED SEAT ACTIVATION WORKFLOW (INVITEE FLOW) */}
      {/* ========================================================= */}
      {showActivationModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.4)', backdropFilter: 'blur(8px)', zIndex: 2000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
          <div className="card-clean" style={{ maxWidth: 460, width: '100%', padding: 28 }}>
            <div style={{ textAlign: 'center', marginBottom: 20 }}>
              <div style={{ width: 44, height: 44, borderRadius: 12, background: '#eff6ff', border: '1px solid #bfdbfe', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 12px' }}>
                <Shield size={24} color="#2563eb" />
              </div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 800, color: '#0f172a' }}>
                Activate Organization Seat
              </h2>
              <p style={{ fontSize: '0.78125rem', color: '#64748b', marginTop: 4 }}>
                Welcome to VeloRoster Pro. Set your password to activate your seat.
              </p>
            </div>

            {activationDetails && activationDetails.valid ? (
              <div>
                <div style={{ padding: 12, borderRadius: 8, background: '#f8fafc', border: '1px solid #e2e8f0', marginBottom: 18 }}>
                  <div style={{ fontSize: '0.71875rem', color: '#64748b' }}>Organization:</div>
                  <div style={{ fontSize: '0.875rem', fontWeight: 700, color: '#0f172a' }}>{activationDetails.company_name}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
                    <span style={{ fontSize: '0.71875rem', color: '#64748b' }}>Assigned Role:</span>
                    <span style={{ fontSize: '0.6875rem', fontWeight: 700, padding: '1px 6px', borderRadius: 4, background: activationDetails.role === 'company_admin' ? '#ecfdf5' : '#eff6ff', color: activationDetails.role === 'company_admin' ? '#059669' : '#2563eb' }}>
                      {activationDetails.role === 'company_admin' ? 'Organization Administrator' : 'Team Member'}
                    </span>
                  </div>
                  <div style={{ fontSize: '0.71875rem', color: '#64748b', marginTop: 4 }}>
                    Email: <strong>{activationDetails.email}</strong>
                  </div>
                </div>

                {activationError && (
                  <div style={{ padding: 10, borderRadius: 6, background: '#fef2f2', border: '1px solid #fecaca', color: '#991b1b', fontSize: '0.75rem', marginBottom: 14 }}>
                    {activationError}
                  </div>
                )}

                <form onSubmit={handleActivationSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>Your Full Name</label>
                    <input
                      type="text"
                      className="input-ui"
                      placeholder="e.g. Jordan Miller"
                      value={activationFullName}
                      onChange={e => setActivationFullName(e.target.value)}
                      required
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>Choose Password (min 5 chars)</label>
                    <input
                      type="password"
                      className="input-ui"
                      placeholder="Enter new password"
                      value={activationPassword}
                      onChange={e => setActivationPassword(e.target.value)}
                      required
                      minLength={5}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: 5 }}>Confirm Password</label>
                    <input
                      type="password"
                      className="input-ui"
                      placeholder="Repeat password"
                      value={activationConfirmPassword}
                      onChange={e => setActivationConfirmPassword(e.target.value)}
                      required
                      minLength={5}
                    />
                  </div>

                  <button
                    type="submit"
                    className="btn-ui btn-primary"
                    style={{ height: 42, marginTop: 4 }}
                    disabled={activationLoading}
                  >
                    {activationLoading ? <RefreshCw className="animate-spin" size={16} /> : <Check size={16} />}
                    <span>Activate Seat & Open Studio</span>
                  </button>
                </form>
              </div>
            ) : (
              <div>
                <div style={{ padding: 14, borderRadius: 8, background: '#fef2f2', border: '1px solid #fecaca', color: '#991b1b', fontSize: '0.78125rem', marginBottom: 18, lineHeight: 1.5 }}>
                  <strong>Invalid or Expired Invitation:</strong>
                  <div style={{ marginTop: 4 }}>
                    {activationError || 'This invitation token is not valid, was already accepted, or was revoked by the administrator.'}
                  </div>
                </div>

                <button
                  className="btn-ui btn-secondary"
                  style={{ width: '100%', height: 38 }}
                  onClick={() => setShowActivationModal(false)}
                >
                  Close & Go to Login
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

