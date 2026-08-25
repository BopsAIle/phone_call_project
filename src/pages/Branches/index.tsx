import React, { useState } from 'react'
import { Button, Card } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { BranchList } from './BranchList'
import { BranchForm } from './BranchForm'
import { Branch } from '../../types'

export const BranchesPage: React.FC = () => {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingBranch, setEditingBranch] = useState<Branch | null>(null)

  const handleCreate = () => {
    setEditingBranch(null)
    setIsModalOpen(true)
  }

  const handleEdit = (branch: Branch) => {
    setEditingBranch(branch)
    setIsModalOpen(true)
  }

  const handleCancel = () => {
    setIsModalOpen(false)
    setEditingBranch(null)
  }

  return (
    <div>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '24px',
        paddingBottom: '16px',
        borderBottom: '1px solid #f0f0f0',
      }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '24px', fontWeight: 600, color: '#001529' }}>
            Quản lý chi nhánh
          </h2>
          <p style={{ margin: '8px 0 0 0', color: 'rgba(0, 0, 0, 0.45)', fontSize: '14px' }}>
            Quản lý và cấu hình chi nhánh các nhà hàng
          </p>
        </div>
        <Button 
          type="primary" 
          size="large"
          icon={<PlusOutlined />} 
          onClick={handleCreate}
          style={{ borderRadius: '6px' }}
        >
          Thêm chi nhánh
        </Button>
      </div>

      <Card>
        <BranchList onEdit={handleEdit} />
      </Card>

      <BranchForm
        open={isModalOpen}
        onCancel={handleCancel}
        initialData={editingBranch}
      />
    </div>
  )
}
