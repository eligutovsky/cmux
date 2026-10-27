import Foundation
import CmuxNextCompat
import Testing
@testable import CmuxNextAgentPane

/// Red half of the fix: base resolves the person's ~/.acpmux in a test process.
struct AcpmuxTestHomeGuardTests {
    static let executable = URL(fileURLWithPath: "/usr/bin/true")

    static func resolve(build: BuildIdentity?, _ environment: [String: String]) -> AcpmuxEnvironment? {
        AcpmuxEnvironment.resolve(build: build, bundledBinDirectory: nil, environment: environment,
                                  isExecutable: { _ in true }, executableOverride: executable, teamIdentifier: nil)
    }

    @Test func aTestThatNamesNoHomeNeverGetsThePersonsDaemon() {
        #expect(Self.resolve(build: nil, [:]) == nil)
        #expect(Self.resolve(build: BuildIdentity(bundleID: "com.cmuxterm.app.debug.guard", bundledTag: nil), [:]) == nil)
        let persons = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".acpmux").path
        #expect(Self.resolve(build: nil, ["ACPMUX_HOME": persons]) == nil)
    }
}
