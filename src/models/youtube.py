from typing import Any, TypedDict


class ClientResource(TypedDict):
    imageName: str


class ImageSource(TypedDict):
    url: str | None
    width: int | None
    height: int | None
    clientResource: ClientResource | None


class Image(TypedDict):
    sources: list[ImageSource]


class RendererContext(TypedDict):
    accessibilityContext: dict[str, str] | None


class ThumbnailBadgeViewModel(TypedDict):
    text: str | None
    badgeStyle: str | None
    animationActivationTargetId: str | None
    animationActivationEntityKey: str | None
    lottieData: dict[str, str | dict[str, Any]] | None
    animatedText: str | None
    animationActivationEntitySelectorType: str | None
    rendererContext: RendererContext | None
    icon: Image | None
    backgroundColor: dict[str, int] | None


class ThumbnailOverlayBadgeViewModel(TypedDict):
    thumbnailBadges: list[dict[str, ThumbnailBadgeViewModel]]
    position: str


class ButtonViewModel(TypedDict):
    iconName: str
    onTap: dict[str, Any] | None
    accessibilityText: str
    style: str
    trackingParams: str
    type: str
    buttonSize: str
    state: str


class ToggleButtonViewModel(TypedDict):
    defaultButtonViewModel: dict[str, ButtonViewModel]
    toggledButtonViewModel: dict[str, ButtonViewModel]
    isToggled: bool
    trackingParams: str


class ThumbnailHoverOverlayToggleActionsViewModel(TypedDict):
    buttons: list[dict[str, ToggleButtonViewModel]]


class ThumbnailHoverOverlayViewModel(TypedDict):
    icon: Image
    text: dict[str, str | list[Any]]
    style: str


class ThumbnailOverlay(TypedDict):
    thumbnailOverlayBadgeViewModel: ThumbnailOverlayBadgeViewModel | None
    thumbnailHoverOverlayToggleActionsViewModel: ThumbnailHoverOverlayToggleActionsViewModel | None
    thumbnailHoverOverlayViewModel: ThumbnailHoverOverlayViewModel | None


class ThumbnailViewModel(TypedDict):
    image: Image
    overlays: list[ThumbnailOverlay]
    backgroundColor: dict[str, int] | None


class CollectionThumbnailViewModel(TypedDict):
    primaryThumbnail: dict[str, ThumbnailViewModel]
    stackColor: dict[str, int]


class ContentImage(TypedDict):
    thumbnailViewModel: ThumbnailViewModel | None
    collectionThumbnailViewModel: CollectionThumbnailViewModel | None


class AvatarViewModel(TypedDict):
    image: Image
    avatarImageSize: str


class DecoratedAvatarViewModel(TypedDict):
    avatar: dict[str, AvatarViewModel]
    a11yLabel: str
    rendererContext: dict[str, Any]


class TextContent(TypedDict):
    content: str
    styleRuns: list[dict[str, Any]] | None
    attachmentRuns: list[dict[str, Any]] | None


class MetadataPart(TypedDict):
    text: TextContent


class MetadataRow(TypedDict):
    metadataParts: list[MetadataPart]


class ContentMetadataViewModel(TypedDict):
    metadataRows: list[MetadataRow]
    delimiter: str


class MenuButtonViewModel(TypedDict):
    iconName: str
    onTap: dict[str, Any]
    accessibilityText: str
    style: str
    trackingParams: str
    type: str
    buttonSize: str
    state: str


class LockupMetadataViewModel(TypedDict):
    title: TextContent
    image: dict[str, DecoratedAvatarViewModel] | None
    metadata: dict[str, ContentMetadataViewModel]
    menuButton: dict[str, MenuButtonViewModel] | None


class Metadata(TypedDict):
    lockupMetadataViewModel: LockupMetadataViewModel


class LoggingDirectives(TypedDict):
    trackingParams: str
    visibility: dict[str, str]


class LoggingContext(TypedDict):
    loggingDirectives: LoggingDirectives


class CommandContext(TypedDict):
    onTap: dict[str, Any]


class LockupRendererContext(TypedDict):
    loggingContext: LoggingContext
    accessibilityContext: dict[str, str] | None
    commandContext: CommandContext | None


class LockupViewModel(TypedDict):
    contentImage: ContentImage
    metadata: Metadata
    contentId: str
    contentType: str
    rendererContext: LockupRendererContext


class YouTubeRelatedVideo(TypedDict):
    lockupViewModel: LockupViewModel


YouTubeRelatedVideosResponse = list[YouTubeRelatedVideo]
