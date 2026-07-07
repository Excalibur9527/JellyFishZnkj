import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { AssetEditPageBase } from './components/AssetEditPageBase'
import { assetAdapters } from './assetAdapters'
import { decodeAssetEditReturnTo } from '../project/ProjectWorkbench/utils/workbenchAssetReturnTo'

export default function CharacterAssetEditPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { characterId } = useParams<{ characterId: string }>()
  const adapter = assetAdapters.character
  const backTo = decodeAssetEditReturnTo(searchParams.get('returnTo'), '/assets?tab=character')

  return (
    <AssetEditPageBase<any, any>
      assetId={characterId}
      onNavigate={(to, replace) => navigate(to, replace ? { replace: true } : undefined)}
      {...adapter}
      backTo={backTo}
    />
  )
}
