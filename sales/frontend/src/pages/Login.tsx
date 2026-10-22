import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { ArrowLeft, ArrowRight, Eye, EyeOff } from 'lucide-react';
import { Logo } from '../components/layout/Sidebar';
import { useLogin, useSetupStatus } from '../hooks/useAuth';
import { launcherUrl } from '../utils/hosts';

const schema = z.object({
  username: z.string().trim().min(1, 'Enter your username').max(80),
  password: z.string().min(1, 'Enter your password').max(200),
});
type Form = z.infer<typeof schema>;

function PreviewCard() {
  const bars = [38, 52, 44, 92, 60, 70, 56];
  return (
    <div className="relative w-[340px] h-[380px]" aria-hidden>
      <div className="absolute inset-0 rounded-[36px] bg-gradient-to-br from-lime-deep/60 to-s2 border border-lime/20 rotate-[9deg] translate-x-8" />
      <div className="absolute inset-0 rounded-[36px] bg-s1 border border-line p-7 -rotate-[4deg] shadow-2xl flex flex-col">
        <div className="text-sm text-mute">Training Pipeline</div>
        <div className="mt-5 space-y-2 text-[13px] text-mute"><div>Company → Decision maker → Training match</div><div>Every fact with its source</div></div>
        <div className="flex items-end gap-2 h-28 mt-auto">
          {bars.map((h, i) => (
            <div key={i} className={`flex-1 rounded-xl ${i === 3 ? 'hatch' : 'bg-s3'}`} style={{ height: `${h}%` }} />
          ))}
        </div>
      </div>
    </div>
  );
}

export default function Login() {
  const login = useLogin();
  const [show, setShow] = useState(false);
  const { register, handleSubmit, formState: { errors } } = useForm<Form>({ resolver: zodResolver(schema) });
  const setup = useSetupStatus(true).data;

  return (
    <div className="min-h-screen grid lg:grid-cols-[1.1fr_1fr]">
      <div className="hidden lg:flex relative flex-col justify-between p-12 border-r border-line overflow-hidden bg-[radial-gradient(ellipse_at_20%_80%,rgba(211,242,90,0.16),transparent_55%)]">
        <Logo />
        <div className="flex items-center justify-center py-10"><PreviewCard /></div>
        <div>
          <h1 className="h-display text-5xl leading-[1.02] max-w-lg">Find the companies ready to train their people.</h1>
          <p className="text-mute mt-4 max-w-md">Corporate Training Prospecting Platform — discover, qualify and convert training opportunities across Johor, Klang Valley, Penang and Singapore.</p>
        </div>
      </div>
      <div className="flex items-center justify-center p-6 sm:p-12">
        <form onSubmit={handleSubmit((v) => login.mutate(v))} className="w-full max-w-[400px]" aria-label="Sign in" noValidate>
          <div className="lg:hidden mb-10"><Logo /></div>
          <a href={launcherUrl} className="inline-flex items-center gap-1.5 text-sm text-mute hover:text-fg mb-8"><ArrowLeft size={15} />All programs</a>
          <div className="eyebrow mb-3">Lead Intelligence</div>
          <h2 className="h-display text-4xl">Sign in</h2>
          <p className="text-sm text-mute mt-2">Corporate Training Prospecting Platform</p>
          <div className="mt-8 space-y-4">
            <div>
              <label htmlFor="username" className="label block mb-1.5">Username</label>
              <input id="username" type="text" autoComplete="username" className="input h-12 rounded-2xl" aria-invalid={!!errors.username} {...register('username')} />
              {errors.username && <p className="text-xs text-danger mt-1">{errors.username.message}</p>}
            </div>
            <div>
              <label htmlFor="pw" className="label block mb-1.5">Password</label>
              <div className="relative">
                <input id="pw" type={show ? 'text' : 'password'} autoComplete="current-password" className="input h-12 rounded-2xl pr-12" aria-invalid={!!errors.password} {...register('password')} />
                <button type="button" onClick={() => setShow((s) => !s)} className="absolute right-2 top-1/2 -translate-y-1/2 w-9 h-9 rounded-full text-mute hover:text-fg flex items-center justify-center" aria-label={show ? 'Hide password' : 'Show password'}>
                  {show ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {errors.password && <p className="text-xs text-danger mt-1">{errors.password.message}</p>}
            </div>
            {login.error && <p role="alert" className="text-sm text-danger">{login.error.message}</p>}
            <button type="submit" className="btn-primary w-full h-12 text-[15px]" disabled={login.isPending}>{login.isPending ? 'Signing in…' : <>Sign In <ArrowRight size={16} /></>}</button>
          </div>
          <div className="mt-8 p-4 rounded-2xl border border-line bg-s1 text-xs text-mute leading-relaxed">
            {setup?.needs_setup
              ? <><span className="text-fg">No accounts yet.</span> Create the first (director) account in <a className="text-lime underline" href={setup.finance_url}>Finance</a>, then sign in here with it.</>
              : <>Use your Codencode Finance account. Accounts are managed by the director in Finance → Team.</>}
          </div>
        </form>
      </div>
    </div>
  );
}
