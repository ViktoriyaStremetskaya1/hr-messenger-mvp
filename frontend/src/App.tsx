import { Center, Loader } from '@mantine/core';
import { Navigate, Route, Routes } from 'react-router-dom';

import { useAuth } from './auth';
import Layout from './components/Layout';
import AuditPage from './pages/Audit';
import CandidatesPage from './pages/Candidates';
import LoginPage from './pages/Login';
import SettingsPage from './pages/Settings';
import UsersPage from './pages/Users';
import VacanciesPage from './pages/Vacancies';

export default function App() {
  const { user, loading, can } = useAuth();
  if (loading)
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  if (!user)
    return (
      <Routes>
        <Route path="*" element={<LoginPage />} />
      </Routes>
    );
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to="/candidates" replace />} />
        <Route path="/candidates" element={<CandidatesPage />} />
        <Route path="/vacancies" element={<VacanciesPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        {can('admin') && <Route path="/users" element={<UsersPage />} />}
        {can('admin', 'lead') && <Route path="/audit" element={<AuditPage />} />}
        <Route path="*" element={<Navigate to="/candidates" replace />} />
      </Route>
    </Routes>
  );
}
