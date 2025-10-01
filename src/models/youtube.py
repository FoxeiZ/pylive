from typing import Dict, List, Optional, TypedDict, Union


class ClientResource(TypedDict):
    imageName: str


class ImageSource(TypedDict):
    url: Optional[str]
    width: Optional[int]
    height: Optional[int]
    clientResource: Optional[ClientResource]


class Image(TypedDict):
    sources: List[ImageSource]


class RendererContext(TypedDict):
    accessibilityContext: Optional[Dict[str, str]]


class ThumbnailBadgeViewModel(TypedDict):
    text: Optional[str]
    badgeStyle: Optional[str]
    animationActivationTargetId: Optional[str]
    animationActivationEntityKey: Optional[str]
    lottieData: Optional[Dict[str, Union[str, Dict]]]
    animatedText: Optional[str]
    animationActivationEntitySelectorType: Optional[str]
    rendererContext: Optional[RendererContext]
    icon: Optional[Image]
    backgroundColor: Optional[Dict[str, int]]


class ThumbnailOverlayBadgeViewModel(TypedDict):
    thumbnailBadges: List[Dict[str, ThumbnailBadgeViewModel]]
    position: str


class ButtonViewModel(TypedDict):
    iconName: str
    onTap: Optional[Dict]
    accessibilityText: str
    style: str
    trackingParams: str
    type: str
    buttonSize: str
    state: str


class ToggleButtonViewModel(TypedDict):
    defaultButtonViewModel: Dict[str, ButtonViewModel]
    toggledButtonViewModel: Dict[str, ButtonViewModel]
    isToggled: bool
    trackingParams: str


class ThumbnailHoverOverlayToggleActionsViewModel(TypedDict):
    buttons: List[Dict[str, ToggleButtonViewModel]]


class ThumbnailHoverOverlayViewModel(TypedDict):
    icon: Image
    text: Dict[str, Union[str, List]]
    style: str


class ThumbnailOverlay(TypedDict):
    thumbnailOverlayBadgeViewModel: Optional[ThumbnailOverlayBadgeViewModel]
    thumbnailHoverOverlayToggleActionsViewModel: Optional[
        ThumbnailHoverOverlayToggleActionsViewModel
    ]
    thumbnailHoverOverlayViewModel: Optional[ThumbnailHoverOverlayViewModel]


class ThumbnailViewModel(TypedDict):
    image: Image
    overlays: List[ThumbnailOverlay]
    backgroundColor: Optional[Dict[str, int]]


class CollectionThumbnailViewModel(TypedDict):
    primaryThumbnail: Dict[str, ThumbnailViewModel]
    stackColor: Dict[str, int]


class ContentImage(TypedDict):
    thumbnailViewModel: Optional[ThumbnailViewModel]
    collectionThumbnailViewModel: Optional[CollectionThumbnailViewModel]


class AvatarViewModel(TypedDict):
    image: Image
    avatarImageSize: str


class DecoratedAvatarViewModel(TypedDict):
    avatar: Dict[str, AvatarViewModel]
    a11yLabel: str
    rendererContext: Dict


class TextContent(TypedDict):
    content: str
    styleRuns: Optional[List[Dict]]
    attachmentRuns: Optional[List[Dict]]


class MetadataPart(TypedDict):
    text: TextContent


class MetadataRow(TypedDict):
    metadataParts: List[MetadataPart]


class ContentMetadataViewModel(TypedDict):
    metadataRows: List[MetadataRow]
    delimiter: str


class MenuButtonViewModel(TypedDict):
    iconName: str
    onTap: Dict
    accessibilityText: str
    style: str
    trackingParams: str
    type: str
    buttonSize: str
    state: str


class LockupMetadataViewModel(TypedDict):
    title: TextContent
    image: Optional[Dict[str, DecoratedAvatarViewModel]]
    metadata: Dict[str, ContentMetadataViewModel]
    menuButton: Optional[Dict[str, MenuButtonViewModel]]


class Metadata(TypedDict):
    lockupMetadataViewModel: LockupMetadataViewModel


class LoggingDirectives(TypedDict):
    trackingParams: str
    visibility: Dict[str, str]


class LoggingContext(TypedDict):
    loggingDirectives: LoggingDirectives


class CommandContext(TypedDict):
    onTap: Dict


class LockupRendererContext(TypedDict):
    loggingContext: LoggingContext
    accessibilityContext: Optional[Dict[str, str]]
    commandContext: Optional[CommandContext]


class LockupViewModel(TypedDict):
    contentImage: ContentImage
    metadata: Metadata
    contentId: str
    contentType: str
    rendererContext: LockupRendererContext


class YouTubeRelatedVideo(TypedDict):
    lockupViewModel: LockupViewModel


YouTubeRelatedVideosResponse = List[YouTubeRelatedVideo]
