import React, { useState, useEffect } from 'react';
import { Company, User } from '../types';
import { Users, UserPlus, X, Trash2, Mail, Check, AlertCircle } from 'lucide-react';

interface TeamModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentUser: User | null;
}

export const TeamModal: React.FC<TeamModalProps> = ({ isOpen, onClose, currentUser }) => {
  const [tab, setTab] = useState<'members' | 'invite' | 'bulk'>('members');
  const [members, setMembers] = useState<any[]>([]);
  const [company, setCompany] = useState<Company | null>(null);
  const [loading, setLoading] = useState(false);

  // Single Invite form
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteName, setInviteName] = useState('');
  const [inviteRole, setInviteRole] = useState<'member' | 'company_admin'>('member');
  const [inviteMsg, setInviteMsg] = useState('');

  // Bulk Invite
  const [bulkText, setBulkText] = useState('');
  const [bulkMsg, setBulkMsg] = useState('');

  const fetchMembers = async () => {
    try {
      setLoading(true);
      const res = await fetch('/api/company/users');
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        setMembers(data.users || []);
        setCompany(data.company || null);
      }
    } catch (e) {
      console.error('Failed to load team members', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchMembers();
    }
  }, [isOpen]);

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setInviteMsg('');
    try {
      const res = await fetch('/api/company/users/invite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: inviteEmail.trim(),
          name: inviteName.trim(),
          role: inviteRole
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        setInviteMsg(`Invited ${inviteEmail} successfully!`);
        setInviteEmail('');
        setInviteName('');
        fetchMembers();
        setTimeout(() => setTab('members'), 1200);
      } else {
        alert(data.detail || data.message || 'Invitation failed.');
      }
    } catch (e: any) {
      alert(`Error: ${e.message}`);
    }
  };

  const handleBulkInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setBulkMsg('');
    try {
      const res = await fetch('/api/company/users/bulk_invite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_text: bulkText })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        setBulkMsg(`Invited ${data.invited_count} users successfully!`);
        setBulkText('');
        fetchMembers();
        setTimeout(() => setTab('members'), 1200);
      } else {
        alert(data.detail || data.message || 'Bulk invite failed.');
      }
    } catch (e: any) {
      alert(`Error: ${e.message}`);
    }
  };

  const handleDeleteUser = async (userId: string) => {
    if (!confirm('Are you sure you want to remove this user seat?')) return;
    try {
      const res = await fetch('/api/company/users/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
      });
      if (res.ok) {
        fetchMembers();
      } else {
        const data = await res.json();
        alert(data.detail || data.message || 'Could not delete user.');
      }
    } catch (e: any) {
      alert(`Error: ${e.message}`);
    }
  };

  if (!isOpen) return null;

  const used = company?.used_seats || members.length;
  const max = company?.max_seats || 10;
  const pct = Math.min(100, Math.round((used / max) * 100));

  return (
    <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal-card" style={{ maxWidth: 760 }}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              width: 34,
              height: 34,
              borderRadius: 8,
              background: 'var(--brand-accent-subtle)',
              border: '1px solid var(--brand-accent-border)',
              color: 'var(--brand-accent)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <Users size={18} />
            </div>
            <div>
              <h3 className="modal-title">{company?.name || 'Organization'} &bull; Team & Seats</h3>
              <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Manage seated user licenses and invitations</p>
            </div>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose}><X size={18} /></button>
        </div>

        <div className="modal-body">
          {/* Seat Quota Meter Card */}
          <div className="saas-card" style={{ padding: 16, marginBottom: 18 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <span style={{ fontSize: '0.82rem', fontWeight: 700 }}>Seat License Allocation</span>
              <span style={{ fontSize: '0.78rem', fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--brand-accent)' }}>
                {used} / {max} Seats Occupied ({max - used} Available)
              </span>
            </div>
            <div style={{ width: '100%', height: 8, background: '#e2e8f0', borderRadius: 4, overflow: 'hidden' }}>
              <div style={{ width: `${pct}%`, height: '100%', background: 'var(--brand-accent)', transition: 'width 0.3s ease' }} />
            </div>
          </div>

          {/* Tab Switcher */}
          <div className="workflow-segmented-bar" style={{ marginBottom: 18 }}>
            <button
              className={`workflow-tab-btn ${tab === 'members' ? 'active' : ''}`}
              onClick={() => setTab('members')}
            >
              <Users size={14} />
              <span>Team Members ({members.length})</span>
            </button>
            <button
              className={`workflow-tab-btn ${tab === 'invite' ? 'active' : ''}`}
              onClick={() => setTab('invite')}
            >
              <UserPlus size={14} />
              <span>Invite Member</span>
            </button>
            <button
              className={`workflow-tab-btn ${tab === 'bulk' ? 'active' : ''}`}
              onClick={() => setTab('bulk')}
            >
              <span>Bulk CSV Paste</span>
            </button>
          </div>

          {/* View 1: Members Table */}
          {tab === 'members' && (
            <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 8, overflow: 'hidden' }}>
              <table className="saas-table">
                <thead>
                  <tr>
                    <th>Member</th>
                    <th>Role</th>
                    <th>Status</th>
                    <th style={{ textAlign: 'right' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {members.map((m) => (
                    <tr key={m.id}>
                      <td>
                        <div style={{ fontWeight: 700, fontSize: '0.86rem' }}>{m.full_name || 'Member'}</div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{m.email}</div>
                      </td>
                      <td>
                        <span style={{
                          fontSize: '0.72rem',
                          fontWeight: 700,
                          textTransform: 'uppercase',
                          padding: '2px 8px',
                          borderRadius: 4,
                          background: m.role === 'company_admin' ? '#eff6ff' : '#f1f5f9',
                          color: m.role === 'company_admin' ? '#1d4ed8' : '#475569'
                        }}>
                          {m.role === 'company_admin' ? 'Admin' : 'Member'}
                        </span>
                      </td>
                      <td>
                        <span style={{
                          fontSize: '0.72rem',
                          fontWeight: 700,
                          color: m.is_active ? 'var(--success)' : 'var(--text-muted)'
                        }}>
                          {m.invite_token ? 'Pending Invite' : (m.is_active ? 'Active' : 'Deactivated')}
                        </span>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {m.id !== currentUser?.id && m.role !== 'superadmin' && (
                          <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => handleDeleteUser(m.id)}
                            title="Remove member seat"
                          >
                            <Trash2 size={14} color="#ef4444" />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* View 2: Single Invite */}
          {tab === 'invite' && (
            <form onSubmit={handleInvite} style={{ maxWidth: 440, margin: '0 auto', textAlign: 'left' }}>
              <div className="saas-form-group">
                <label className="saas-form-label">Email Address</label>
                <input
                  type="email"
                  className="saas-input"
                  placeholder="editor@organization.com"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  required
                />
              </div>

              <div className="saas-form-group">
                <label className="saas-form-label">Full Name</label>
                <input
                  type="text"
                  className="saas-input"
                  placeholder="e.g. Alex Morgan"
                  value={inviteName}
                  onChange={(e) => setInviteName(e.target.value)}
                />
              </div>

              <div className="saas-form-group">
                <label className="saas-form-label">Role</label>
                <select
                  className="saas-input"
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as any)}
                >
                  <option value="member">Regular Member (Studio Workbench)</option>
                  <option value="company_admin">Organization Administrator</option>
                </select>
              </div>

              {inviteMsg && (
                <div style={{
                  padding: '10px 14px',
                  background: 'var(--success-subtle)',
                  border: '1px solid var(--success-border)',
                  color: 'var(--success)',
                  borderRadius: 'var(--r-md)',
                  fontSize: '0.82rem',
                  fontWeight: 600,
                  marginBottom: 16
                }}>
                  {inviteMsg}
                </div>
              )}

              <button
                type="submit"
                className="btn btn-primary"
                style={{ width: '100%', padding: '10px' }}
                disabled={used >= max}
              >
                <span>{used >= max ? 'Seat Limit Reached' : 'Send Invitation'}</span>
              </button>
            </form>
          )}

          {/* View 3: Bulk CSV */}
          {tab === 'bulk' && (
            <form onSubmit={handleBulkInvite} style={{ maxWidth: 500, margin: '0 auto', textAlign: 'left' }}>
              <div className="saas-form-group">
                <label className="saas-form-label">Paste CSV, TSV, or Emails</label>
                <p style={{ fontSize: '0.74rem', color: 'var(--text-muted)', marginBottom: 8 }}>
                  Format: <code>email@example.com, Full Name, member</code> (one per line)
                </p>
                <textarea
                  className="saas-input"
                  rows={6}
                  placeholder={`sarah@company.com, Sarah Connor, member\njohn@company.com, John Reese, member`}
                  value={bulkText}
                  onChange={(e) => setBulkText(e.target.value)}
                  required
                />
              </div>

              {bulkMsg && (
                <div style={{
                  padding: '10px 14px',
                  background: 'var(--success-subtle)',
                  border: '1px solid var(--success-border)',
                  color: 'var(--success)',
                  borderRadius: 'var(--r-md)',
                  fontSize: '0.82rem',
                  fontWeight: 600,
                  marginBottom: 16
                }}>
                  {bulkMsg}
                </div>
              )}

              <button
                type="submit"
                className="btn btn-primary"
                style={{ width: '100%', padding: '10px' }}
              >
                <span>Process Bulk Invitations</span>
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};
