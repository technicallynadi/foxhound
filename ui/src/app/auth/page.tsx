import { redirect } from 'next/navigation';

/**
 * /auth is not available during early access.
 * Redirect to the waitlist page.
 */
export default function AuthRedirect() {
  redirect('/login');
}
