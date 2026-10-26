export interface Company {
  id: string;
  name: string;
  slug: string;
  plan: string;
  max_seats: number;
  used_seats: number;
  remaining_seats: number;
  status: string;
}

export interface User {
  id: string;
  company_id: string | null;
  email: string;
  full_name: string;
  role: 'superadmin' | 'company_admin' | 'member';
  is_superadmin: boolean;
  mfa_enabled: boolean;
  passkeys_count: number;
  is_active: number | boolean;
  created_at?: string;
  company: Company | null;
}

export interface Player {
  name: string;
  number?: string;
  assigned_number?: string;
  position?: string;
  pos?: string;
  height?: string;
  weight?: string;
  years?: string;
  team?: string;
  image?: string;
  url?: string;
}

export interface PhotoOption {
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

export interface SuggestedFolder {
  name: string;
  full_path: string;
  photo_count: number;
}
