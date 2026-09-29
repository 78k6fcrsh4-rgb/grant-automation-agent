import { useState } from 'react';
import type { FormEvent } from 'react';
import { useNavigate, Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

/** Why signing in failed, distinguished by layer.
 *
 * These used to collapse into one message, and it cost an afternoon: a
 * backend that was not running looked exactly like a wrong password, so the
 * password got reset — twice — while the real problem was that nothing was
 * listening on port 8000. Only 401 and 403 are about what the person typed.
 * Everything else is about the system, and saying so is the difference
 * between checking a log and doubting your own credentials.
 *
 * The 401 text still comes from the server, which deliberately returns one
 * message for unknown organisation, unknown email and wrong password so the
 * platform cannot be used to enumerate which nonprofits are on it.
 */
function describeLoginFailure(err: any): string {
  const status = err?.response?.status;
  if (status === undefined) {
    return 'Cannot reach the server — it may not be running. Your credentials have not been checked yet.';
  }
  if (status === 401 || status === 403) {
    return err?.response?.data?.detail ?? 'Incorrect organisation, email or password.';
  }
  if (status === 422) {
    return 'The server rejected the shape of this request, which usually means the app and the server are different versions.';
  }
  if (status >= 500) {
    return `The server failed while signing in (HTTP ${status}). This is not a problem with what you typed — check the backend log.`;
  }
  return err?.response?.data?.detail ?? `Sign in failed (HTTP ${status}).`;
}

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  // Prefilled from the last successful sign-in on this browser. A name, not
  // a credential; the token lives elsewhere and is not read here.
  const [organization, setOrganization] = useState(() => {
    try {
      return localStorage.getItem('gma.organization') ?? '';
    } catch {
      return '';
    }
  });
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(organization.trim().toLowerCase(), email.trim().toLowerCase(), password);
      navigate('/', { replace: true });
    } catch (err: any) {
      setError(describeLoginFailure(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md bg-white rounded-xl shadow-sm border border-gray-200 p-8">
        <h1 className="text-2xl font-semibold text-gray-900">Grant Award Management</h1>
        <p className="mt-1 text-sm text-gray-500">Sign in to continue</p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">Organisation</label>
            <input
              type="text"
              required
              autoComplete="organization"
              autoFocus
              placeholder="e.g. dupage"
              value={organization}
              onChange={(e) => setOrganization(e.target.value)}
              className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            />
            <p className="mt-1 text-xs text-gray-500">
              The short name your organisation was set up under. Ask whoever
              set up your account if you are not sure.
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Email</label>
            <input
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Password</label>
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            />
          </div>

          {error && (
            <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-blue-600 px-4 py-2 text-white font-medium hover:bg-blue-700 disabled:opacity-60"
          >
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  );
}
