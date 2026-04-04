import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HomePage } from './pages/HomePage';
import { GrantDetailsPage } from './pages/GrantDetailsPage';
import { GrantListPage } from './pages/GrantListPage';

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
      <Router>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/grants" element={<GrantListPage />} />
          <Route path="/grant/:fileId" element={<GrantDetailsPage />} />
        </Routes>
      </Router>
    </QueryClientProvider>
  );
}

export default App;