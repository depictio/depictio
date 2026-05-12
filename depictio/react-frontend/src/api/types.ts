export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expire_datetime: string;
  refresh_expire_datetime: string;
  user_id: string;
  name?: string;
  logged_in: boolean;
}

export interface User {
  id: string;
  email: string;
  is_admin: boolean;
  is_active: boolean;
  is_verified: boolean;
  is_anonymous: boolean;
  last_login?: string;
  registration_date?: string;
}

export interface DashboardPermissions {
  owners: Array<{ id: string; email: string }>;
  editors: Array<{ id: string; email: string }>;
  viewers: Array<{ id: string; email: string } | string>;
}

export interface Dashboard {
  dashboard_id: string;
  title: string;
  subtitle?: string;
  icon?: string;
  icon_color?: string;
  is_public: boolean;
  project_id: string;
  version?: number;
  is_main_tab?: boolean;
  parent_dashboard_id?: string | null;
  tab_order?: number;
  permissions?: DashboardPermissions;
}
