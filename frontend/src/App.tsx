import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HomePage } from './pages/HomePage';
import { GrantDetailsPage } from './pages/GrantDetailsPage';
import { GrantListPage } from './pages/GrantListPage';
import { ExtractionReviewPage } from './pages/ExtractionReviewPage';
import { LoginPage } from './pages/LoginPage';
import { AuthProvider } from './context/AuthContext';
import { ProtectedRoute } from './components/ProtectedRoute';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 5 * 60 * 1000, // 5 minutes
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Router>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<ProtectedRoute><HomePage /></ProtectedRoute>} />
            <Route path="/grants" element={<ProtectedRoute><GrantListPage /></ProtectedRoute>} />
            <Route path="/grant/:fileId" element={<ProtectedRoute><GrantDetailsPage /></ProtectedRoute>} />
            <Route path="/grant/:fileId/review" element={<ProtectedRoute><ExtractionReviewPage /></ProtectedRoute>} />
          </Routes>
        </Router>
      </AuthProvider>
    </QueryClientProvider>
  );
}

export default App;
