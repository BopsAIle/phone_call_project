import React, { useState } from 'react'
import { Layout, Menu, MenuProps, theme } from 'antd'
import { HomeOutlined, ShopOutlined, BranchesOutlined, CalendarOutlined, UnorderedListOutlined, ShoppingCartOutlined, MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import { APP_NAME } from '../../utils/constants'

interface MainLayoutProps {
  children: React.ReactNode
}

type MenuItem = Required<MenuProps>['items'][number]

const items: MenuItem[] = [
  {
    key: '/',
    icon: <HomeOutlined style={{ fontSize: '16px' }} />,
    label: 'Dashboard',
  },
  {
    key: '/restaurants',
    icon: <ShopOutlined style={{ fontSize: '16px' }} />,  
    label: 'Nhà hàng',
  },
  {
    key: '/branches',
    icon: <BranchesOutlined style={{ fontSize: '16px' }} />,
    label: 'Chi nhánh',
  },
  {
    key: '/menu',
    icon: <UnorderedListOutlined style={{ fontSize: '16px' }} />,
    label: 'Thực đơn',
  },
  {
    key: '/orders',
    icon: <ShoppingCartOutlined style={{ fontSize: '16px' }} />,
    label: 'Đơn hàng',
  },
  {
    key: '/bookings',
    icon: <CalendarOutlined style={{ fontSize: '16px' }} />,
    label: 'Đặt bàn',
  },
]

export const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
  const navigate = useNavigate()
  const location = useLocation()
  const { token } = theme.useToken()
  const [collapsed, setCollapsed] = useState(false)

  const handleMenuClick: MenuProps['onClick'] = (e) => {
    navigate(e.key)
  }

  return (
    <Layout style={{ minHeight: '100vh', background: '#f5f7fa' }}>
      <Layout.Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        style={{
          position: 'fixed',
          left: 0,
          top: 0,
          bottom: 0,
          overflow: 'auto',
          background: '#001529',
          boxShadow: '2px 0 8px rgba(0, 0, 0, 0.1)',
          zIndex: 999,
        }}
        width={220}
        collapsedWidth={80}
      >
        <div
          style={{
            padding: '20px 16px',
            textAlign: 'center',
            borderBottom: '1px solid rgba(255, 255, 255, 0.15)',
            marginBottom: '16px',
          }}
        >
          <div
            style={{
              color: '#1677ff',
              fontSize: '24px',
              fontWeight: 'bold',
              textAlign: 'center',
            }}
          >
            {collapsed ? '🍽️' : 'Restaurant AI'}
          </div>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          onClick={handleMenuClick}
          selectedKeys={[location.pathname]}
          items={items}
          style={{
            background: 'transparent',
            borderRight: 'none',
          }}
        />
      </Layout.Sider>

      <Layout style={{ marginLeft: collapsed ? 80 : 220, transition: 'margin-left 0.2s' }}>
        <Layout.Header
          style={{
            background: '#ffffff',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            boxShadow: '0 2px 8px rgba(0, 0, 0, 0.06)',
            borderBottom: `1px solid ${token.colorBorder}`,
            height: 64,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <button
              onClick={() => setCollapsed(!collapsed)}
              style={{
                background: 'none',
                border: 'none',
                fontSize: '18px',
                cursor: 'pointer',
                color: '#001529',
              }}
            >
              {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            </button>
            <h1 style={{ margin: 0, fontSize: '18px', fontWeight: 600, color: '#001529' }}>
              {APP_NAME}
            </h1>
          </div>
        </Layout.Header>

        <Layout.Content
          style={{
            padding: '24px',
            background: '#f5f7fa',
            minHeight: 'calc(100vh - 64px)',
          }}
        >
          <div
            style={{
              background: token.colorBgContainer,
              padding: '24px',
              borderRadius: '8px',
              boxShadow: '0 1px 2px 0 rgba(0, 0, 0, 0.03)',
              minHeight: '100%',
            }}
          >
            {children}
          </div>
        </Layout.Content>

        <Layout.Footer
          style={{
            textAlign: 'center',
            color: 'rgba(0, 0, 0, 0.45)',
            fontSize: '12px',
            background: '#fafafa',
            borderTop: `1px solid ${token.colorBorder}`,
            marginTop: 'auto',
            padding: '12px 24px',
          }}
        >
          <div style={{ marginBottom: '4px' }}>
            <strong>Restaurant AI Management</strong> © 2026
          </div>
          <div style={{ fontSize: '11px' }}>Quản lý nhà hàng thông minh với AI</div>
        </Layout.Footer>
      </Layout>
    </Layout>
  )
}
