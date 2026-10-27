import React from 'react';
import { User } from '../types';
import { Layers, Shield, Building2, Users, LogOut, Search, Globe, SlidersHorizontal, UserCircle2 } from 'lucide-react';

interface NavbarProps {
  user: User | null;
  activeTab: 'search' | 'roster' | 'workbench';
  onTabChange: (tab: 'search' | 'roster' | 'workbench') => void;
  onOpenTeam: () => void;
  onOpenSuperAdmin: () => void;
  onOpenAccount: () => void;
  onLogout: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  user,
  activeTab,
  onTabChange,
  onOpenTeam,
  onOpenSuperAdmin,
  onOpenAccount,
  onLogout
}) => {
  if (!user) return null;

  const isSuperAdmin = user.is_superadmin || user.role === 'superadmin';
  const isCompanyAdmin = user.role === 'company_admin';
  const company = user.company;

  return (
    <header className="app-navbar">
      {/* Brand & Left Section */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div className="nav-brand">
          <div className="nav-logo-icon">
            <Layers size={18} strokeWidth={2.4} />
          </div>
          <span className="nav-title">
            VeloRoster <span>AI</span>
          </span>
        </div>

        {isSuperAdmin ? (
          <span className="badge-pill badge-brand" style={{ fontSize: '0.72rem' }}>
            SuperAdmin
          </span>
        ) : company ? (
          <span className="badge-pill badge-neutral" style={{ fontSize: '0.72rem' }}>
            <Building2 size={12} />
            <span>{company.name}</span>
          </span>
        ) : null}
      </div>

      {/* Center: Main Workflow Tabs */}
      <nav className="nav-tabs">
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === 'search' ? 'active' : ''}`}
          onClick={() => onTabChange('search')}
        >
          <Search size={14} />
          <span>Athlete Search</span>
        </button>
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === 'roster' ? 'active' : ''}`}
          onClick={() => onTabChange('roster')}
        >
          <Globe size={14} />
          <span>Team Scraper</span>
        </button>
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === 'workbench' ? 'active' : ''}`}
          onClick={() => onTabChange('workbench')}
        >
          <SlidersHorizontal size={14} />
          <span>180×180 Studio</span>
        </button>
      </nav>

      {/* Right Controls & Profile */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        {/* Seat Usage Indicator for Organizations */}
        {!isSuperAdmin && company && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onOpenTeam}
            title="Manage Team & Seats"
            style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}
          >
            <Users size={14} />
            <span>{company.used_seats} / {company.max_seats} Seats</span>
          </button>
        )}

        {/* SuperAdmin Organization Hub */}
        {isSuperAdmin && (
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onOpenSuperAdmin}
            style={{ fontSize: '0.75rem' }}
          >
            <Shield size={14} color="#2563eb" />
            <span>Fleet Hub</span>
          </button>
        )}

        {/* Account Settings */}
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={onOpenAccount}
          title="Account Security & Passkeys"
        >
          <UserCircle2 size={16} />
        </button>

        {/* Logout */}
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={onLogout}
          title="Sign Out"
          style={{ color: 'var(--text-muted)' }}
        >
          <LogOut size={16} />
        </button>
      </div>
    </header>
  );
};
