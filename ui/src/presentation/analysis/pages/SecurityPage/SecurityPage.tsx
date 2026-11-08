import {
  Button,
  DataTable,
  Lede,
  Notice,
  SpecList,
  Value,
} from '@/presentation/shared/components'
import { describe } from '@/presentation/shared/formatters'
import { useCurrentInventory } from '@/presentation/shared/hooks/useCurrentInventory'
import { useElevation } from '@/presentation/shared/hooks/useElevation'
import { ModuleMissing } from '../../components/ModuleMissing/ModuleMissing'
import { NoInventory } from '../../components/NoInventory/NoInventory'
import {
  antivirusColumns,
  encryptionColumns,
  firewallColumns,
} from '../../formatters/systemColumns'
import { defenderSpecs, securitySpecs } from '../../formatters/systemSpecs'

export function SecurityPage() {
  const { inventory } = useCurrentInventory()
  const { isElevated, requestElevation } = useElevation()
  const security = inventory?.security ?? null

  return (
    <>
      <h1>Seguridad</h1>
      <Lede>
        Honey Check solo lee estos estados. No cambia ninguna configuración.
      </Lede>
      {!inventory ? <NoInventory /> : null}
      {inventory && !security ? (
        <ModuleMissing module="security" label="seguridad" />
      ) : null}
      {security ? (
        <>
          <SpecList rows={securitySpecs(security)} />

          <h2 id="antivirus" tabIndex={-1}>
            Antivirus
          </h2>
          {security.antivirusStatus.value ? (
            <DataTable
              columns={antivirusColumns}
              rows={security.antivirus}
              rowKey={(product) => product.name.value ?? 'antivirus'}
              emptyText="Windows no reporta antivirus registrados."
            />
          ) : (
            <Value display={describe(security.antivirusStatus)} />
          )}
          {security.defender ? (
            <>
              <h3>Microsoft Defender</h3>
              <SpecList rows={defenderSpecs(security.defender)} />
            </>
          ) : null}

          <h2 id="firewall" tabIndex={-1}>
            Firewall
          </h2>
          <DataTable
            columns={firewallColumns}
            rows={security.firewallProfiles}
            rowKey={(profile) => profile.name}
            emptyText="Windows no reportó perfiles de firewall."
          />

          <h2 id="cifrado" tabIndex={-1}>
            Cifrado de volúmenes
          </h2>
          {security.volumeEncryptionStatus.value ? (
            <DataTable
              columns={encryptionColumns}
              rows={security.volumeEncryption}
              rowKey={(volume) => volume.driveLetter}
              emptyText="Windows no reportó volúmenes cifrables."
            />
          ) : (
            <Notice>
              <p>
                Cifrado:{' '}
                <Value display={describe(security.volumeEncryptionStatus)} />
              </p>
              {isElevated ? null : (
                <Button size="small" onClick={requestElevation}>
                  Ejecutar como administrador
                </Button>
              )}
            </Notice>
          )}
        </>
      ) : null}
    </>
  )
}
