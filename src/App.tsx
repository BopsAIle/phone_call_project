import React from 'react'
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import { QueryClientProvider, QueryClient } from '@tanstack/react-query'
import { ConfigProvider } from 'antd'
import viVN from 'antd/locale/vi_VN'
import { MainLayout } from './components'
import { Dashboard, RestaurantsPage, BranchesPage, BookingsPage } from './pages'

const queryClient = new QueryClient()

const customTheme = {
  token: {
    colorPrimary: '#1677ff',
    borderRadius: 8,
    fontFamily: `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif`,
    fontSize: 14,
    colorSuccess: '#52c41a',
    colorWarning: '#faad14',
    colorError: '#ff4d4f',
    colorInfo: '#1677ff',
    colorBgBase: '#ffffff',
  },
  components: {
    Layout: {
      siderBg: '#001529',
      headerBg: '#ffffff',
      headerHeight: 64,
      headerPadding: '0 24px',
      headerColor: 'rgba(0, 0, 0, 0.85)',
      headerBorderBottom: '1px solid #f0f0f0',
    },
    Menu: {
      itemBg: 'transparent',
      itemHoverBg: 'rgba(255, 255, 255, 0.1)',
      itemSelectedBg: '#1677ff',
      itemSelectedColor: '#fff',
      itemHeight: 40,
    },
    Button: {
      borderRadius: 6,
      controlHeight: 36,
      fontWeight: 500,
    },
    Card: {
      boxShadow: '0 1px 2px 0 rgba(0, 0, 0, 0.03), 0 1px 6px -1px rgba(0, 0, 0, 0.02), 0 2px 4px 0 rgba(0, 0, 0, 0.02)',
      borderRadiusLG: 8,
    },
    Table: {
      headerBg: '#fafafa',
      headerBorderRadius: 0,
      borderColor: '#f0f0f0',
      rowHoverBg: '#f5f5f5',
    },
    Input: {
      borderRadius: 6,
      controlHeight: 36,
    },
    Select: {
      borderRadius: 6,
      controlHeight: 36,
    },
    Modal: {
      borderRadiusLG: 8,
    },
    Tag: {
      borderRadiusSM: 4,
    },
  },
}

const App: React.FC = () => {
  return (
    <ConfigProvider theme={customTheme} locale={viVN} componentSize="large">
      <QueryClientProvider client={queryClient}>
        <Router>
          <MainLayout>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/restaurants" element={<RestaurantsPage />} />
              <Route path="/branches" element={<BranchesPage />} />
              <Route path="/bookings" element={<BookingsPage />} />
            </Routes>
          </MainLayout>
        </Router>
      </QueryClientProvider>
    </ConfigProvider>
  )
}

export default App
