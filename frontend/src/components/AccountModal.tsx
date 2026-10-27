import React, { useState, useEffect } from 'react';
import { User } from '../types';
import { KeyRound, Shield, Fingerprint, X, Trash2, Check, AlertCircle } from 'lucide-react';

interface AccountModalProps {
  isOpen?: boolean;
  onClose: () => void;
  currentUser?: User | null;
  user?: User | null;
  onUserUpdated?: (user: User) => void;
}

export const AccountModal: React.FC<AccountModalProps> = ({
  isOpen = true,
  onClose,
  currentUser,
  user,
  onUserUpdated
}) => {
  const [tab, setTab] = useState<'password' | 'passkeys'>('password');

  // Password state
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordMsg, setPasswordMsg] = useState('');
  const [passwordErr, setPasswordErr] = useState('');

  // Passkeys state
  const [passkeys, setPasskeys] = useState<any[]>([]);
  const [passkeyLoading, setPasskeyLoading] = useState(false);

  const fetchPasskeys = async () => {
    try {
      setPasskeyLoading(true);
      const res = await fetch('/api/auth/passkey/list');
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        setPasskeys(data.passkeys || []);
      }
    } catch (e) {
      console.error('Failed to load passkeys', e);
    } finally {
      setPasskeyLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchPasskeys();
    }
  }, [isOpen]);

  const handlePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordMsg('');
    setPasswordErr('');

    if (newPassword.length < 6) {
      setPasswordErr('New password must be at least 6 characters.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordErr('Passwords do not match.');
      return;
    }

    try {
      const res = await fetch('/api/auth/update_credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword
        })
      });
      const data = await res.json();

      if (res.ok && data.status === 'ok') {
        setPasswordMsg('Password updated successfully!');
        setCurrentPassword('');
        setNewPassword('');
        setConfirmPassword('');
        if (data.user && onUserUpdated) onUserUpdated(data.user);
      } else {
        setPasswordErr(data.detail || data.message || 'Failed to update password.');
      }
    } catch (e: any) {
      setPasswordErr(e.message || 'Error updating password.');
    }
  };

  const handleDeletePasskey = async (id: string) => {
    try {
      const res = await fetch('/api/auth/passkey/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ passkey_id: id })
      });
      if (res.ok) {
        fetchPasskeys();
      }
    } catch (e) {
      console.error(e);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal-card" style={{ maxWidth: 580 }}>
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
              <KeyRound size={18} />
            </div>
            <div>
              <h3 className="modal-title">Account Security & Credentials</h3>
              <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Password, Passkeys & Biometric Keys</p>
            </div>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose}><X size={18} /></button>
        </div>

        <div className="modal-body">
          {/* Tab Switcher */}
          <div className="workflow-segmented-bar" style={{ marginBottom: 20 }}>
            <button
              className={`workflow-tab-btn ${tab === 'password' ? 'active' : ''}`}
              onClick={() => setTab('password')}
            >
              <KeyRound size={14} />
              <span>Password & Profile</span>
            </button>
            <button
              className={`workflow-tab-btn ${tab === 'passkeys' ? 'active' : ''}`}
              onClick={() => setTab('passkeys')}
            >
              <Fingerprint size={14} />
              <span>Biometric Passkeys ({passkeys.length})</span>
            </button>
          </div>

          {/* Tab 1: Password Update */}
          {tab === 'password' && (
            <form onSubmit={handlePasswordSubmit} style={{ maxWidth: 440, margin: '0 auto', textAlign: 'left' }}>
              <div className="saas-form-group">
                <label className="saas-form-label">Email Address (Read-only)</label>
                <input
                  type="email"
                  className="saas-input"
                  value={currentUser?.email || ''}
                  disabled
                  style={{ background: '#f8fafc', color: 'var(--text-muted)' }}
                />
              </div>

              <div className="saas-form-group">
                <label className="saas-form-label">Current Password</label>
                <input
                  type="password"
                  className="saas-input"
                  placeholder="••••••••"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  required
                />
              </div>

              <div className="saas-form-group">
                <label className="saas-form-label">New Password</label>
                <input
                  type="password"
                  className="saas-input"
                  placeholder="Minimum 6 characters"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                />
              </div>

              <div className="saas-form-group">
                <label className="saas-form-label">Confirm New Password</label>
                <input
                  type="password"
                  className="saas-input"
                  placeholder="Repeat new password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                />
              </div>

              {passwordMsg && (
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
                  {passwordMsg}
                </div>
              )}

              {passwordErr && (
                <div style={{
                  padding: '10px 14px',
                  background: 'var(--danger-subtle)',
                  border: '1px solid var(--danger-border)',
                  color: 'var(--danger)',
                  borderRadius: 'var(--r-md)',
                  fontSize: '0.82rem',
                  fontWeight: 600,
                  marginBottom: 16
                }}>
                  {passwordErr}
                </div>
              )}

              <button
                type="submit"
                className="btn btn-primary"
                style={{ width: '100%', padding: '10px' }}
              >
                <span>Update Password</span>
              </button>
            </form>
          )}

          {/* Tab 2: Passkeys */}
          {tab === 'passkeys' && (
            <div>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: 16 }}>
                Passkeys allow you to sign in securely using Touch ID, Face ID, or Windows Hello without typing a password.
              </p>

              {passkeys.length === 0 ? (
                <div style={{ textAlign: 'center', padding: 24, color: 'var(--text-muted)', fontSize: '0.84rem' }}>
                  No biometric passkeys registered yet.
                </div>
              ) : (
                <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 8, overflow: 'hidden' }}>
                  <table className="saas-table">
                    <thead>
                      <tr>
                        <th>Key Name</th>
                        <th>Registered</th>
                        <th style={{ textAlign: 'right' }}>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {passkeys.map((k) => (
                        <tr key={k.id}>
                          <td>
                            <div style={{ fontWeight: 700, fontSize: '0.86rem', display: 'flex', alignItems: 'center', gap: 6 }}>
                              <Fingerprint size={14} color="#2563eb" />
                              <span>{k.name}</span>
                            </div>
                            <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                              {(k.credential_id || '').substring(0, 24)}...
                            </div>
                          </td>
                          <td style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                            {k.created_at ? new Date(k.created_at).toLocaleDateString() : 'N/A'}
                          </td>
                          <td style={{ textAlign: 'right' }}>
                            <button
                              className="btn btn-ghost btn-sm"
                              onClick={() => handleDeletePasskey(k.id)}
                            >
                              <Trash2 size={14} color="#ef4444" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
