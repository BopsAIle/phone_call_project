import React from 'react'
import { Spin } from 'antd'

interface LoadingSpinnerProps {
  loading?: boolean
  size?: 'small' | 'default' | 'large'
}

export const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({ loading = true, size = 'large' }) => {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', minHeight: '300px' }}>
      <Spin size={size} spinning={loading} />
    </div>
  )
}
